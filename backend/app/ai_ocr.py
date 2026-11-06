import os
import json
import google.generativeai as genai
from PIL import Image
from .config import settings

# Configure Gemini
genai.configure(api_key=settings.gemini_api_key)

def read_labels_with_ai(image_path: str) -> list[dict]:
    """Reads labels from an image using Gemini Vision and returns bounding boxes."""
    img = Image.open(image_path)
    
    prompt = """
    You are a medical OCR assistant. Look at this lecture slide.
    Find ONLY short text labels that point to a specific structure in a diagram or image (e.g., "Vagus nerve", "Right marginal artery"). 
    DO NOT return:
    - Slide titles (e.g., "SURFACE PROJECTION OF THE TRACHEA")
    - Bullet points or paragraphs (e.g., "• through its lower division")
    - Page numbers
    - Any text longer than 6 words.

    Return ONLY a JSON array of objects. Each object must have:
    - "text": the exact text of the label.
    - "ymin": top coordinate (0.0 to 1.0)
    - "xmin": left coordinate (0.0 to 1.0)
    - "ymax": bottom coordinate (0.0 to 1.0)
    - "xmax": right coordinate (0.0 to 1.0)
    """
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([prompt, img])
    
    try:
        # Clean up the response (sometimes it wraps in markdown)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        
        data = json.loads(text)
        
        # Convert 0-1000 coordinates to 0.0-1.0 fractions
        labels = []
        for item in data:
            labels.append({
                "text": item["text"],
                "x0": float(item["xmin"]),
                "y0": float(item["ymin"]),
                "x1": float(item["xmax"]),
                "y1": float(item["ymax"]),
                "confidence": 100.0
            })
        return labels
    except Exception as e:
        print(f"AI OCR failed: {e}")
        print(response.text)
        return []