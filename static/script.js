const imageInput = document.getElementById('imageInput');
const audioInput = document.getElementById('audioInput');
const mixedInput = document.getElementById('mixedInput');
const imageLabel = document.getElementById('imageLabel');
const audioLabel = document.getElementById('audioLabel');
const preview = document.getElementById('preview');
const result = document.getElementById('result');
const resultText = document.getElementById('resultText');
const nextBtn = document.getElementById('nextBtn');
const status = document.getElementById('status');
const recordBtn = document.getElementById('recordBtn');
const stopBtn = document.getElementById('stopBtn');
const dropzone = document.getElementById('dropzone');
const browseBtn = document.getElementById('browseBtn');

let modelsLoaded = false;
let mediaRecorder = null;
let recordedChunks = [];
let activeStream = null;

const audioSupported = Boolean(
    navigator.mediaDevices &&
    navigator.mediaDevices.getUserMedia &&
    window.MediaRecorder
);

function setStatus(type, message) {
    status.className = `status ${type}`;
    status.textContent = message;
}

function stopActiveStream() {
    if (!activeStream) {
        return;
    }

    activeStream.getTracks().forEach((track) => track.stop());
    activeStream = null;
}

function resetRecorderButtons() {
    recordBtn.disabled = !audioSupported;
    stopBtn.disabled = true;
}

function renderResultCard(title, metaParts) {
    const meta = metaParts
        .filter(Boolean)
        .map((part) => `<span>${part}</span>`)
        .join('');

    return `
        <div class="result-item">
            <strong>${title}</strong>
            <div class="result-meta">${meta}</div>
        </div>
    `;
}

function handleSelectedFile(file) {
    if (!file) {
        return;
    }

    if (file.type.startsWith('image/')) {
        classifyImage(file);
        return;
    }

    if (file.type.startsWith('audio/')) {
        classifyAudio(file);
        return;
    }

    setStatus('error', 'Unsupported file type. Upload an image or audio file.');
}

// Check models status on page load
function checkStatus() {
    fetch('/status')
        .then((response) => response.json())
        .then((data) => {
            modelsLoaded = data.loaded;
            if (modelsLoaded) {
                setStatus('success', 'Image model loaded. Audio uses BirdNET on demand.');
                imageLabel.style.opacity = '1';
                audioLabel.style.opacity = '1';
            } else if (data.error) {
                setStatus('error', `Model loading failed: ${data.error}`);
            } else if (data.loading) {
                setStatus('loading', 'Loading models...');
                setTimeout(checkStatus, 2000);
            } else {
                setStatus('loading', 'Starting model loading...');
                setTimeout(checkStatus, 2000);
            }
        })
        .catch(() => {
            setStatus('error', 'Unable to reach the server.');
        });
}

checkStatus();
resetRecorderButtons();

if (!audioSupported) {
    recordBtn.textContent = 'Recording Unavailable';
}

browseBtn.addEventListener('click', () => {
    mixedInput.click();
});

dropzone.addEventListener('click', () => {
    mixedInput.click();
});

dropzone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        mixedInput.click();
    }
});

['dragenter', 'dragover'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add('dragover');
    });
});

['dragleave', 'drop'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove('dragover');
    });
});

dropzone.addEventListener('drop', (event) => {
    const [file] = event.dataTransfer.files;
    handleSelectedFile(file);
});

mixedInput.addEventListener('change', () => {
    handleSelectedFile(mixedInput.files[0]);
    mixedInput.value = '';
});

imageInput.addEventListener('change', () => {
    if (imageInput.files[0]) {
        classifyImage(imageInput.files[0]);
    }
});

audioInput.addEventListener('change', () => {
    if (audioInput.files[0]) {
        classifyAudio(audioInput.files[0]);
    }
});

function classifyImage(file) {
    if (!modelsLoaded) {
        setStatus('error', 'Models are not loaded yet.');
        return;
    }

    setStatus('loading', 'Processing image...');
    result.classList.add('hidden');

    const reader = new FileReader();
    reader.onload = (e) => {
        preview.innerHTML = `<img src="${e.target.result}" alt="Preview">`;
        preview.classList.add('active');
    };
    reader.readAsDataURL(file);

    const formData = new FormData();
    formData.append('file', file);

    fetch('/classify-image', {
        method: 'POST',
        body: formData
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.error) {
                setStatus('error', data.error);
            } else {
                setStatus('success', 'Image classification complete.');
                resultText.innerHTML = renderResultCard(
                    data.species,
                    ['Image scan complete', 'Top visual match']
                );
                result.classList.remove('hidden');
            }
        })
        .catch((error) => {
            setStatus('error', 'Error processing image.');
            console.error(error);
        });
}

function classifyAudio(file) {
    setStatus('loading', 'Processing audio...');
    result.classList.add('hidden');

    const previewUrl = URL.createObjectURL(file);
    preview.innerHTML = `
        <div>
            <p>Audio ready: ${file.name}</p>
            <audio controls src="${previewUrl}"></audio>
        </div>
    `;
    preview.classList.add('active');

    const formData = new FormData();
    formData.append('file', file);

    fetch('/classify-audio', {
        method: 'POST',
        body: formData
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.error) {
                setStatus('error', data.error);
            } else if (data.rejected || !data.candidates?.length) {
                setStatus('error', data.message || 'No confident bird calls detected.');
            } else {
                setStatus('success', 'Audio classification complete.');
                resultText.innerHTML = data.candidates
                    .map((candidate, index) => {
                        const confidence = Math.round(candidate.confidence * 100);
                        const timeRange = `${candidate.start_time.toFixed(1)}s - ${candidate.end_time.toFixed(1)}s`;
                        return renderResultCard(
                            `${index + 1}. ${candidate.species}`,
                            [`Confidence ${confidence}%`, `Window ${timeRange}`]
                        );
                    })
                    .join('');
                result.classList.remove('hidden');
            }
        })
        .catch((error) => {
            setStatus('error', 'Error processing audio.');
            console.error(error);
        });
}

recordBtn.addEventListener('click', async () => {
    if (!audioSupported) {
        setStatus('error', 'This browser does not support microphone recording.');
        return;
    }

    try {
        activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];
        mediaRecorder = new MediaRecorder(activeStream);

        mediaRecorder.addEventListener('dataavailable', (event) => {
            if (event.data.size > 0) {
                recordedChunks.push(event.data);
            }
        });

        mediaRecorder.addEventListener('stop', () => {
            const mimeType = mediaRecorder.mimeType || 'audio/webm';
            const extension = mimeType.includes('ogg') ? 'ogg' : 'webm';
            const audioBlob = new Blob(recordedChunks, { type: mimeType });
            const audioFile = new File([audioBlob], `recording.${extension}`, { type: mimeType });

            resetRecorderButtons();
            stopActiveStream();
            classifyAudio(audioFile);
        });

        mediaRecorder.start();
        recordBtn.disabled = true;
        stopBtn.disabled = false;
        setStatus('loading', 'Recording from microphone...');
        preview.innerHTML = '<p>Microphone is recording. Click "Stop Recording" when ready.</p>';
        preview.classList.add('active');
    } catch (error) {
        stopActiveStream();
        resetRecorderButtons();
        setStatus('error', 'Microphone access was denied or unavailable.');
        console.error(error);
    }
});

stopBtn.addEventListener('click', () => {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        return;
    }

    setStatus('loading', 'Finishing recording...');
    stopBtn.disabled = true;
    mediaRecorder.stop();
});

nextBtn.addEventListener('click', () => {
    stopActiveStream();
    preview.innerHTML = '';
    preview.classList.remove('active');
    result.classList.add('hidden');
    imageInput.value = '';
    audioInput.value = '';
    resetRecorderButtons();
    setStatus('success', 'Ready for the next prediction.');
});
