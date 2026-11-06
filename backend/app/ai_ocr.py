import os
import json
import google.generativeai as genai
from PIL import Image
from .config import settings

genai.configure(api_key=settings.gemini_api_key)

def read_labels_with_ai(image_path: str) -> list[dict]:
    img = Image.open(image_path)
    
    prompt = """
    You are a medical OCR assistant. Look at this lecture slide.
    Return every piece of text on the page. For each item, give a "role":
    - "diagram_label": a short name attached to a structure inside a figure (1 to 5 words, often with a line/arrow).
    - "title": a heading or slide title.
    - "body": sentences, bullet points, or lists.
    - "caption": text starting with Figure or Fig.
    - "other": anything else.

    Return ONLY JSON: {"items":[{"text": "...", "role": "...", "xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0}]}
    """
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([prompt, img])
    
    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        
        data = json.loads(text)
        
        labels = []
        for item in data.get("items", []):
            labels.append({
                "text": item.get("text", ""),
                "role": item.get("role", "other"),
                "x0": float(item.get("xmin", 0)),
                "y0": float(item.get("ymin", 0)),
                "x1": float(item.get("xmax", 0)),
                "y1": float(item.get("ymax", 0)),
                "confidence": 100.0
            })
        return labels
    except Exception as e:
        print(f"AI OCR failed: {e}")
        print(response.text) # <--- This will print what Gemini actually sent back
        return []