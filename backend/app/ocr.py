import fitz
from sqlalchemy import select, delete
from .models import LabelRegion, PageRender
from .ai_ocr import read_labels_with_ai

class OcrUnavailable(Exception):
    pass

MIN_CONF_AUTO = 70.0

def get_pdf_text_boxes(pdf_path, page_number):
    """Extracts all words and their coordinates from the PDF text layer."""
    boxes = []
    try:
        with fitz.open(pdf_path) as doc:
            if page_number > len(doc):
                return boxes
            page = doc[page_number - 1]
            words = page.get_text("words")
            for w in words:
                x0, y0, x1, y1, text, *_ = w
                boxes.append({
                    "text": text.lower().strip(),
                    "x0": x0 / page.rect.width,
                    "y0": y0 / page.rect.height,
                    "x1": x1 / page.rect.width,
                    "y1": y1 / page.rect.height
                })
    except Exception as e:
        print(f"Could not read PDF text layer: {e}")
    return boxes

def is_heading_or_text(label, pdf_boxes):
    """Checks if the label overlaps with existing text in the PDF."""
    if not pdf_boxes:
        return False
        
    label_text = label["text"].lower().strip()
    
    for box in pdf_boxes:
        # If the text is exactly the same or contains each other
        if label_text in box["text"] or box["text"] in label_text:
            # Check if the coordinates overlap significantly
            # If they overlap, it's a heading or body text.
            if (label["x0"] < box["x1"] and label["x1"] > box["x0"] and 
                label["y0"] < box["y1"] and label["y1"] > box["y0"]):
                return True
    return False

def ocr_page_regions(db, page: PageRender) -> int:
    from .models import Source
    source = db.get(Source, page.source_id)
    if not source:
        return 0
    # 1. Get everything Gemini sees on the image
    found = read_labels_with_ai(page.file_path)
    
    # 2. Get every word from the PDF text layer
    pdf_boxes = get_pdf_text_boxes(page.stored_path, page.page_number)
    
    # 3. Clear old labels
    db.execute(delete(LabelRegion).where(LabelRegion.page_id == page.id))
    
    created = 0
    for item in found:
        text = item["text"].strip()
        
        # Filter 1: Too long (likely a sentence)
        if len(text.split()) > 6:
            continue
            
        # Filter 2: Junk (single letters, numbers)
        if len(text) < 3 or text.isdigit():
            continue
            
        # Filter 3: The Magic Subtraction
        # Filter 3: The Magic Subtraction
        if is_heading_or_text(item, pdf_boxes):
            db.add(LabelRegion(
                page_id=page.id, user_id=page.user_id,
                x0=item["x0"], y0=item["y0"], x1=item["x1"], y1=item["y1"],
                text=text, origin="ocr", status="rejected",
                confidence=100.0, reject_reason="pdf_text"
            ))
            continue
            
        # If it survives all filters, it's a true diagram label!
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