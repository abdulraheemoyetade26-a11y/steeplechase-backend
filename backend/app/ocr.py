import fitz
from sqlalchemy import select, delete
from .models import LabelRegion, PageRender
from .ai_ocr import read_labels_with_ai

class OcrUnavailable(Exception):
    pass

MIN_CONF_AUTO = 70.0

def get_pdf_heading_texts(pdf_path, page_number):
    """Extracts only the LARGE text (headings) from the PDF."""
    headings = set()
    try:
        with fitz.open(pdf_path) as doc:
            if page_number > len(doc): return headings
            page = doc[page_number - 1]
            blocks = page.get_text("dict")["blocks"]
            
            for b in blocks:
                if b["type"] != 0: continue # Skip images
                for line in b["lines"]:
                    for span in line["spans"]:
                        # If the font size is large (e.g., > 14), it's a heading
                        if span["size"] > 14:
                            headings.add(span["text"].lower().strip())
    except Exception as e:
        print(f"Could not read PDF text layer: {e}")
    return headings

def ocr_page_regions(db, page: PageRender) -> int:
    from .models import Source
    source = db.get(Source, page.source_id)
    if not source: return 0
    
    # 1. Tesseract finds EVERY word on the image
    found = read_labels_with_ai(page.file_path)
    
    # 2. Get the headings from the PDF
    pdf_headings = get_pdf_heading_texts(source.stored_path, page.page_number)
    
    # 3. Clear old labels
    db.execute(delete(LabelRegion).where(LabelRegion.page_id == page.id))
    
    created = 0
    for item in found:
        text = item["text"].strip()
        
        # Filter 1: Too long
        if len(text.split()) > 6 or len(text) > 40:
            continue
            
        # Filter 2: Junk
        if len(text) < 3 or text.isdigit():
            continue
            
        # Filter 3: Is it a heading from the PDF?
        is_heading = False
        for h in pdf_headings:
            if text.lower() in h or h in text.lower():
                is_heading = True
                break
                
        if is_heading:
            db.add(LabelRegion(
                page_id=page.id, user_id=page.user_id,
                x0=item["x0"], y0=item["y0"], x1=item["x1"], y1=item["y1"],
                text=text, origin="ocr", status="rejected",
                confidence=100.0, reject_reason="pdf_heading"
            ))
            continue
            
        # If it survives, keep it!
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