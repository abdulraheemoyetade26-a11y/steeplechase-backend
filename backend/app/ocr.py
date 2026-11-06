import fitz
from sqlalchemy import select, delete
from .models import LabelRegion, PageRender
from .ai_ocr import read_labels_with_ai

class OcrUnavailable(Exception):
    pass
MIN_CONF_AUTO = 70.0

def get_pdf_text_boxes(pdf_path, page_number):
    """Extracts the bounding boxes of all text on a specific page."""
    boxes = []
    try:
        with fitz.open(pdf_path) as doc:
            page = doc[page_number - 1]
            words = page.get_text("words")
            for w in words:
                x0, y0, x1, y1, text, *_ = w
                # Convert PDF points to 0.0 - 1.0 fractions
                boxes.append({
                    "text": text.lower(),
                    "x0": x0 / page.rect.width,
                    "y0": y0 / page.rect.height,
                    "x1": x1 / page.rect.width,
                    "y1": y1 / page.rect.height
                })
    except Exception as e:
        print(f"Could not read PDF text layer: {e}")
    return boxes

def is_heading(label, pdf_boxes):
    """Check if the label's coordinates match a word in the PDF's text layer."""
    for box in pdf_boxes:
        # If the text is similar and the boxes overlap heavily
        if label["text"].lower() in box["text"] or box["text"] in label["text"].lower():
            # Check overlap
            if (label["x0"] < box["x1"] and label["x1"] > box["x0"] and 
                label["y0"] < box["y1"] and label["y1"] > box["y0"]):
                return True
    return False

def ocr_page_regions(db, page: PageRender) -> int:
    found = read_labels_with_ai(page.file_path)
    pdf_boxes = get_pdf_text_boxes(page.file_path, 1) # Assuming 1 page image per PDF page
    
    # Clear old labels for this page
    db.execute(delete(LabelRegion).where(LabelRegion.page_id == page.id))
    
    created = 0
    for item in found:
        text = item["text"].strip()
        
        # Filter 1: Too long (likely a sentence)
        if len(text.split()) > 5:
            continue
            
        # Filter 2: It's a heading from the PDF text layer
        if is_heading(item, pdf_boxes):
            db.add(LabelRegion(
                page_id=page.id, user_id=page.user_id,
                x0=item["x0"], y0=item["y0"], x1=item["x1"], y1=item["y1"],
                text=text, origin="ocr", status="rejected",
                confidence=100.0, reject_reason="heading"
            ))
            continue
            
        # Filter 3: Junk (single letters, numbers)
        if len(text) < 3 or text.isdigit():
            continue
            
        # Keep it!
        db.add(
            LabelRegion(
                page_id=page.id, user_id=page.user_id,
                x0=item["x0"], y0=item["y0"], x1=item["x1"], y1=item["y1"],
                text=text, origin="ocr", status="auto",
                confidence=100.0
            )
        )
        created += 1
        
    page.ocr_done = True
    return created

def run_ocr_for_source(db, source_id: int, page_numbers: list[int] | None = None) -> dict:
    query = select(PageRender).where(PageRender.source_id == source_id, PageRender.ocr_done.is_(False))
    if page_numbers:
        query = query.where(PageRender.page_number.in_(page_numbers))
    pages = db.scalars(query.order_by(PageRender.page_number)).all()
    
    labels = 0
    for page in pages:
        labels += ocr_page_regions(db, page)
        db.commit()
    return {"pages_processed": len(pages), "labels_found": labels}