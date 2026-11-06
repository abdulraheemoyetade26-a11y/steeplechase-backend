import os
import json
import fitz
from PIL import Image
import pytesseract
from pytesseract import Output
from .config import settings

def read_labels_with_ai(image_path: str) -> list[dict]:
    # We use Tesseract for local, fast, blind text extraction
    try:
        img = Image.open(image_path)
        # Upscale for better accuracy on small text
        img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
        
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        
        labels = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            if not text: continue
            
            # Tesseract gives coordinates in pixels, convert to 0.0-1.0
            x0 = data["left"][i] / img.width
            y0 = data["top"][i] / img.height
            x1 = (data["left"][i] + data["width"][i]) / img.width
            y1 = (data["top"][i] + data["height"][i]) / img.height
            
            labels.append({
                "text": text,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "confidence": 100.0
            })
        return labels
    except Exception as e:
        print(f"Tesseract failed: {e}")
        return []