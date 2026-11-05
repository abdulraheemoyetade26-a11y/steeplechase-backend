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
    Find every short text label (like "Vagus nerve", "Right marginal artery", "Ascending aorta").
    Do NOT return bullet points, long paragraphs, or page numbers.
    Return ONLY a JSON array of objects. Each object must have:
    - "text": the exact text of the label.
    - "ymin": top coordinate (0 to 1000)
    - "xmin": left coordinate (0 to 1000)
    - "ymax": bottom coordinate (0 to 1000)
    - "xmax": right coordinate (0 to 1000)
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