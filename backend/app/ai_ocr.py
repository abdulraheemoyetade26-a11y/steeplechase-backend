import os
import json
import google.generativeai as genai
from PIL import Image
from .config import settings

genai.configure(api_key=settings.gemini_api_key)

def read_labels_with_ai(image_path: str) -> list[dict]:
    img = Image.open(image_path)
    
    prompt = """
    You are a medical OCR assistant. 
    Look at this lecture slide. 
    
    Ignore the main title at the top. Ignore the bullet points and paragraphs.
    
    Your ONLY job is to find the small text labels that are next to a diagram, illustration, or picture. These labels usually have a straight line or arrow pointing to a specific part of the anatomy.
    
    Return ONLY the text labels that are physically attached to the drawing. 
    
    Return ONLY JSON: {"items":[{"text": "...", "xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0}]}
    
    If there are no diagrams or labels on the page, return {"items": []}.
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
                "x0": float(item.get("xmin", 0)),
                "y0": float(item.get("ymin", 0)),
                "x1": float(item.get("xmax", 0)),
                "y1": float(item.get("ymax", 0)),
                "confidence": 100.0
            })
        return labels
    except Exception as e:
        print(f"AI OCR failed: {e}")
        print(response.text)
        return []