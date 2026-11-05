import re
import shutil
import subprocess
from pathlib import Path

import fitz  # PyMuPDF
from sqlalchemy import select

from .config import settings
from .models import LabelRegion, PageRender

TARGET_WIDTH = 1600
MAX_SCALE = 3.0
MAX_LABEL_CHARS = 60
MAX_LABEL_WORDS = 7
TITLE_FRACTION = 0.14
FOOTER_FRACTION = 0.92
NOISE = re.compile(r"^(fig(ure)?|table|slide|page|source|references?|copyright)\b", re.IGNORECASE)


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def pdf_for_source(source) -> Path:
    """Return a PDF path for the source, converting PowerPoint files with LibreOffice when needed."""
    stored = Path(source.stored_path)
    if source.file_type == "pdf":
        return stored
    if source.file_type != "pptx":
        raise ValueError("Page rendering supports PDF and PowerPoint files only")

    out_dir = Path(settings.upload_dir) / str(source.user_id) / "converted" / str(source.id)
    target = out_dir / (stored.stem + ".pdf")
    if target.exists():
        return target

    soffice = find_soffice()
    if soffice is None:
        raise ValueError(
            "LibreOffice was not found, so this PowerPoint cannot be converted. "
            "Save the deck as a PDF from PowerPoint (File, Save As, PDF) and upload that PDF instead."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(stored)],
            capture_output=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("PowerPoint conversion took too long. Try saving the deck as a PDF and uploading that.")
    if not target.exists():
        raise ValueError(
            "PowerPoint conversion failed. Close any open LibreOffice windows and try again, "
            "or save the deck as a PDF and upload that."
        )
    return target


def propose_labels(page) -> list[dict]:
    """Short text blocks on the page are proposed as label boxes (positions as fractions of the page)."""
    rect = page.rect
    proposals = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, _block_no, block_type = block[:7]
        if block_type != 0:
            continue
        clean = " ".join(text.split())
        if len(clean) < 2 or clean.isdigit():
            continue
        if len(clean) > MAX_LABEL_CHARS or len(clean.split()) > MAX_LABEL_WORDS:
            continue
        if NOISE.match(clean):
            continue
        if y1 < rect.height * TITLE_FRACTION or y0 > rect.height * FOOTER_FRACTION:
            continue
        pad = 2
        proposals.append(
            {
                "x0": max(0.0, (x0 - pad) / rect.width),
                "y0": max(0.0, (y0 - pad) / rect.height),
                "x1": min(1.0, (x1 + pad) / rect.width),
                "y1": min(1.0, (y1 + pad) / rect.height),
                "text": clean,
            }
        )
    return proposals

def render_source_pages(db, source, page_numbers: list[int]) -> int:
    """Render the chosen pages to pictures and store proposed label boxes. Returns how many were new."""
    pdf_path = pdf_for_source(source)
    out_dir = Path(settings.upload_dir) / str(source.user_id) / "pages" / str(source.id)
    out_dir.mkdir(parents=True, exist_ok=True)

    already = set(
        db.scalars(select(PageRender.page_number).where(PageRender.source_id == source.id)).all()
    )
    created = 0
    with fitz.open(pdf_path) as doc:
        for number in page_numbers:
            if number < 1 or number > len(doc) or number in already:
                continue
            page = doc[number - 1]
            scale = min(MAX_SCALE, TARGET_WIDTH / page.rect.width)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            file_path = out_dir / f"{number:04d}.jpg"
            pix.save(str(file_path))

            render = PageRender(
                source_id=source.id,
                user_id=source.user_id,
                page_number=number,
                file_path=str(file_path),
                width=pix.width,
                height=pix.height,
            )
            db.add(render)
            db.flush()
            for p in propose_labels(page):
              db.add(
                  LabelRegion(
                      page_id=render.id,
                      user_id=source.user_id,
                      x0=p["x0"],
                      y0=p["y0"],
                      x1=p["x1"],
                      y1=p["y1"],
                      text=p["text"],
                      origin="text",
                      status="auto",
                      confidence=100.0,
                  )
              )
            created += 1
    return created