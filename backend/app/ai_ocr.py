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
    
    Your task is to find ONLY the text labels that point to a specific anatomical structure inside a diagram, picture, or illustration. These labels usually have a line, leader, or arrow pointing from the text to the structure. 
    
    DO NOT return:
    - The main slide title or heading (e.g., "The Aorta").
    - Paragraphs of text, bullet points, or lists.
    - Text that is purely explanatory.
    
    If a page has a diagram, find the small text labels around the diagram (e.g., "Ascending aorta", "Aortic arch", "Brachiocephalic trunk").
    
    Return ONLY JSON: {"items":[{"text": "...", "role": "diagram_label", "xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0}]}
    
    If there are no diagram labels on the page, return {"items": []}.
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
            # If Gemini forgot to include a role, default to 'other'
            role = item.get("role", "other")
            
            labels.append({
                "text": item.get("text", ""),
                "role": role, # <--- Ensure this is always a string
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