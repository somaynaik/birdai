import csv
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from PIL import Image
from werkzeug.utils import secure_filename

import imageio_ffmpeg

app = Flask(__name__)
default_origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "https://avian-map.vercel.app",
]
configured_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", ",".join(default_origins)).split(",")
    if origin.strip()
]

CORS(app, origins=configured_origins)
app.config['UPLOAD_FOLDER'] = os.environ.get(
    "UPLOAD_FOLDER",
    str(Path(tempfile.gettempdir()) / "birdscanner_uploads"),
)
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "50")) * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global variables for models
models = {
    'image_processor': None,
    'image_model': None,
    'loaded': False,
    'loading': False,
    'error': None
}

models_lock = threading.Lock()


def load_models():
    """Load image model in the background once per process."""
    with models_lock:
        if models['loaded'] or models['loading']:
            return
        models['loading'] = True
        models['error'] = None

    try:
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        models['image_processor'] = AutoImageProcessor.from_pretrained("chriamue/bird-species-classifier")
        models['image_model'] = AutoModelForImageClassification.from_pretrained("chriamue/bird-species-classifier")
        models['loaded'] = True
        models['error'] = None
        print("Image model loaded successfully.")
    except Exception as e:
        models['loaded'] = False
        models['error'] = str(e)
        print(f"Error loading image model: {str(e)}")
    finally:
        models['loading'] = False


def ensure_models_loading():
    if models['loaded'] or models['loading']:
        return
    threading.Thread(target=load_models, daemon=True).start()


def model_loading_response():
    if models['error']:
        return jsonify({'error': f"Image model loading failed: {models['error']}"}), 500
    return jsonify({'error': 'Image model is still loading. Try again in a few seconds.'}), 400


def parse_birdnet_results(csv_path, limit=5):
    candidates = []

    if not os.path.exists(csv_path):
        return candidates

    with open(csv_path, newline='', encoding='utf-8') as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            common_name = row.get('Common name', '').strip()
            scientific_name = row.get('Scientific name', '').strip()

            if not common_name and not scientific_name:
                continue

            species_label = common_name or scientific_name
            if scientific_name and common_name:
                species_label = f"{common_name} ({scientific_name})"

            candidates.append({
                'species': species_label,
                'common_name': common_name,
                'scientific_name': scientific_name,
                'confidence': round(float(row.get('Confidence', 0) or 0), 4),
                'start_time': float(row.get('Start (s)', 0) or 0),
                'end_time': float(row.get('End (s)', 0) or 0)
            })

    candidates.sort(key=lambda item: item['confidence'], reverse=True)
    return candidates[:limit]


def decode_with_librosa(source_path):
    import librosa

    audio, sample_rate = librosa.load(source_path, sr=48000, mono=True)
    return audio, sample_rate


def decode_with_ffmpeg(source_path, working_dir):
    normalized_path = os.path.join(working_dir, "normalized.wav")
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        source_path,
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "wav",
        normalized_path,
    ]

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg conversion failed"
        raise ValueError(detail)

    return normalized_path


def decode_with_torchaudio(source_path):
    import numpy as np
    import torchaudio

    waveform, sample_rate = torchaudio.load(source_path)
    if waveform.ndim > 1 and waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    if sample_rate != 48000:
        waveform = torchaudio.functional.resample(waveform, sample_rate, 48000)
        sample_rate = 48000

    audio = waveform.squeeze(0).detach().cpu().numpy().astype(np.float32)
    return audio, sample_rate


def decode_with_soundfile(source_path):
    import librosa
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)

    if isinstance(audio, np.ndarray) and audio.ndim > 1:
        audio = audio.mean(axis=1)

    if sample_rate != 48000:
        audio = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=sample_rate, target_sr=48000)
        sample_rate = 48000

    return np.asarray(audio, dtype=np.float32), sample_rate


def normalize_audio_for_birdnet(source_path, working_dir):
    """Decode uploaded audio with multiple backends and rewrite it as a WAV file for BirdNET."""
    import soundfile as sf

    normalized_path = os.path.join(working_dir, "normalized.wav")
    errors = []

    try:
        return decode_with_ffmpeg(source_path, working_dir)
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        errors.append(f"ffmpeg: {detail}")

    for decoder_name, decoder in (
        ("librosa", decode_with_librosa),
        ("torchaudio", decode_with_torchaudio),
        ("soundfile", decode_with_soundfile),
    ):
        try:
            audio, sample_rate = decoder(source_path)
            if len(audio) == 0:
                raise ValueError("decoded audio is empty")

            sf.write(normalized_path, audio, sample_rate, subtype="PCM_16")
            return normalized_path
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            errors.append(f"{decoder_name}: {detail}")

    raise ValueError("; ".join(errors))


@app.route('/')
def index():
    ensure_models_loading()
    return render_template('index.html')


@app.route('/status')
def status():
    ensure_models_loading()
    return jsonify({
        'loaded': models['loaded'],
        'loading': models['loading'],
        'error': models['error']
    })


@app.route('/classify-image', methods=['POST'])
def classify_image():
    filepath = None
    try:
        import torch

        ensure_models_loading()
        if not models['loaded']:
            return model_loading_response()

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        image = Image.open(filepath).convert("RGB")
        inputs = models['image_processor'](images=image, return_tensors="pt")

        with torch.no_grad():
            outputs = models['image_model'](**inputs)

        logits = outputs.logits
        pred = torch.argmax(logits, dim=-1).item()
        label = models['image_model'].config.id2label[pred]

        return jsonify({'species': label, 'type': 'image'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)


@app.route('/classify-audio', methods=['POST'])
def classify_audio():
    filepath = None
    output_dir = None
    normalized_path = None
    try:
        from birdnet_analyzer.analyze.core import analyze as birdnet_analyze

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        output_dir = tempfile.mkdtemp(prefix='birdnet_')
        try:
            normalized_path = normalize_audio_for_birdnet(filepath, output_dir)
        except Exception as load_error:
            return jsonify({
                'error': (
                    "Could not decode that audio file. Try a WAV or FLAC recording. "
                    f"Details: {str(load_error)}"
                )
            }), 400

        birdnet_analyze(
            audio_input=normalized_path,
            output=output_dir,
            min_conf=0.2,
            top_n=5,
            rtype='csv',
            locale='en',
            threads=2,
            lat=-1,
            lon=-1,
            week=-1,
            show_progress=False
        )

        file_stem = os.path.splitext(os.path.basename(normalized_path))[0]
        csv_path = os.path.join(output_dir, f"{file_stem}.BirdNET.results.csv")
        candidates = parse_birdnet_results(csv_path)

        if not candidates:
            return jsonify({
                'type': 'audio',
                'rejected': True,
                'message': 'No confident bird calls were detected in this recording.',
                'candidates': []
            })

        return jsonify({
            'type': 'audio',
            'rejected': False,
            'candidates': candidates
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        if output_dir and os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == '__main__':
    ensure_models_loading()
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(debug=debug, host='0.0.0.0', port=port)
