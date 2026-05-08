import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import torch
from transformers import AutoImageProcessor, AutoModelForImageClassification
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
import librosa
import threading

class BirdClassifierApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bird Species Classifier")
        self.root.geometry("600x550")
        self.root.configure(bg="#f0f0f0")
        
        self.image_model = None
        self.image_processor = None
        self.audio_model = None
        self.audio_extractor = None
        
        self.setup_ui()
        self.load_models()
    
    def setup_ui(self):
        title_label = tk.Label(
            self.root, 
            text="🐦 Bird Species Classifier", 
            font=("Arial", 20, "bold"),
            bg="#f0f0f0",
            fg="#2c3e50"
        )
        title_label.pack(pady=20)
        
        button_frame = tk.Frame(self.root, bg="#f0f0f0")
        button_frame.pack(pady=20)
        
        self.image_btn = tk.Button(
            button_frame,
            text="📷 Upload Image",
            command=self.upload_image,
            font=("Arial", 12),
            bg="#3498db",
            fg="white",
            padx=20,
            pady=10,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.image_btn.grid(row=0, column=0, padx=10)
        
        self.audio_btn = tk.Button(
            button_frame,
            text="🎵 Upload Audio",
            command=self.upload_audio,
            font=("Arial", 12),
            bg="#e74c3c",
            fg="white",
            padx=20,
            pady=10,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.audio_btn.grid(row=0, column=1, padx=10)
        
        self.preview_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.preview_frame.pack(pady=20)
        
        self.preview_label = tk.Label(
            self.preview_frame,
            text="",
            bg="#f0f0f0",
            font=("Arial", 10)
        )
        self.preview_label.pack()
        
        self.result_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.result_frame.pack(pady=20)
        
        self.result_label = tk.Label(
            self.result_frame,
            text="",
            font=("Arial", 14, "bold"),
            bg="#f0f0f0",
            fg="#27ae60"
        )
        self.result_label.pack()
        
        self.next_btn = tk.Button(
            self.root,
            text="🔄 Next Bird",
            command=self.reset_app,
            font=("Arial", 12),
            bg="#9b59b6",
            fg="white",
            padx=20,
            pady=10,
            relief=tk.RAISED,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.next_btn.pack(pady=10)
        
        self.status_label = tk.Label(
            self.root,
            text="Loading models...",
            font=("Arial", 10),
            bg="#f0f0f0",
            fg="#7f8c8d"
        )
        self.status_label.pack(side=tk.BOTTOM, pady=10)
        
        self.root.bind('<Escape>', lambda e: self.root.quit())
    
    def load_models(self):
        def load():
            try:
                self.image_processor = AutoImageProcessor.from_pretrained("chriamue/bird-species-classifier")
                self.image_model = AutoModelForImageClassification.from_pretrained("chriamue/bird-species-classifier")
                
                self.audio_extractor = AutoFeatureExtractor.from_pretrained("greenarcade/wav2vec2-vd-bird-sound-classification")
                self.audio_model = AutoModelForAudioClassification.from_pretrained("greenarcade/wav2vec2-vd-bird-sound-classification")
                
                self.status_label.config(text="✅ Models loaded successfully!")
                self.image_btn.config(state=tk.NORMAL)
                self.audio_btn.config(state=tk.NORMAL)
            except Exception as e:
                self.status_label.config(text=f"❌ Error loading models: {str(e)}")
                messagebox.showerror("Error", f"Failed to load models: {str(e)}")
        
        self.image_btn.config(state=tk.DISABLED)
        self.audio_btn.config(state=tk.DISABLED)
        threading.Thread(target=load, daemon=True).start()
    
    def upload_image(self):
        file_path = filedialog.askopenfilename(
            title="Select Bird Image",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp"), ("All files", "*.*")]
        )
        
        if file_path:
            self.classify_image(file_path)
    
    def upload_audio(self):
        file_path = filedialog.askopenfilename(
            title="Select Bird Audio",
            filetypes=[("Audio files", "*.wav *.flac *.mp3"), ("All files", "*.*")]
        )
        
        if file_path:
            self.classify_audio(file_path)
    
    def classify_image(self, image_path):
        try:
            self.status_label.config(text="🔄 Processing image...")
            self.result_label.config(text="")
            self.next_btn.config(state=tk.DISABLED)
            
            image = Image.open(image_path).convert("RGB")
            
            img_copy = image.copy()
            img_copy.thumbnail((250, 250))
            photo = ImageTk.PhotoImage(img_copy)
            self.preview_label.config(image=photo, text="")
            self.preview_label.image = photo
            
            inputs = self.image_processor(images=image, return_tensors="pt")
            
            with torch.no_grad():
                outputs = self.image_model(**inputs)
            
            logits = outputs.logits
            pred = torch.argmax(logits, dim=-1).item()
            label = self.image_model.config.id2label[pred]
            
            self.result_label.config(text=f"✅ Predicted Species: {label}")
            self.status_label.config(text="✅ Classification complete!")
            self.next_btn.config(state=tk.NORMAL)
            
        except Exception as e:
            self.status_label.config(text="❌ Error processing image")
            messagebox.showerror("Error", f"Failed to classify image: {str(e)}")
    
    def classify_audio(self, audio_path):
        try:
            self.status_label.config(text="🔄 Processing audio...")
            self.result_label.config(text="")
            self.next_btn.config(state=tk.DISABLED)
            self.preview_label.config(image="", text=f"🎵 Audio: {audio_path.split('/')[-1]}")
            
            # Try loading with soundfile first, then fall back to audioread
            try:
                audio, sr = librosa.load(audio_path, sr=16000, mono=True)
            except Exception as load_error:
                self.status_label.config(text="❌ Error loading audio")
                messagebox.showerror("Error", 
                    f"Could not load audio file.\n\n"
                    f"Supported formats: WAV, FLAC\n"
                    f"Try converting your audio to WAV format.\n\n"
                    f"Technical details: {str(load_error)}")
                return
            
            # Check if audio is valid
            if len(audio) == 0:
                messagebox.showerror("Error", "Audio file is empty or corrupted.")
                self.status_label.config(text="❌ Invalid audio file")
                return
            
            inputs = self.audio_extractor(audio, sampling_rate=sr, return_tensors="pt")
            
            with torch.no_grad():
                outputs = self.audio_model(**inputs)
            
            logits = outputs.logits
            pred_id = torch.argmax(logits, dim=-1).item()
            label = self.audio_model.config.id2label[pred_id]
            
            self.result_label.config(text=f"🎉 Predicted Species: {label}")
            self.status_label.config(text="✅ Classification complete!")
            self.next_btn.config(state=tk.NORMAL)
            
        except Exception as e:
            self.status_label.config(text="❌ Error processing audio")
            messagebox.showerror("Error", f"Failed to classify audio: {str(e)}")
    
    def reset_app(self):
        self.preview_label.config(image="", text="")
        self.preview_label.image = None
        self.result_label.config(text="")
        self.next_btn.config(state=tk.DISABLED)
        self.status_label.config(text="Ready for next prediction")

if __name__ == "__main__":
    root = tk.Tk()
    app = BirdClassifierApp(root)
    root.mainloop()