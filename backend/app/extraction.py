from pathlib import Path

import fitz  # PyMuPDF
from docx import Document
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

MAX_CHUNK_CHARS = 2500
MIN_TOTAL_CHARS = 100


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > max_chars:
            parts.append(current.strip())
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current.strip())
    return parts


def extract_pdf(path: Path):
    units = []
    with fitz.open(path) as doc:
        count = len(doc)
        for number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                units.append(("page", number, text))
    return units, count


def _shape_texts(shape) -> list[str]:
    found = []
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for inner in shape.shapes:
            found.extend(_shape_texts(inner))
    elif getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            found.append(" | ".join(cells))
    elif shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            found.append(text)
    return found


def extract_pptx(path: Path):
    units = []
    prs = Presentation(str(path))
    count = len(prs.slides)
    for number, slide in enumerate(prs.slides, start=1):
        parts = []
        for shape in slide.shapes:
            parts.extend(_shape_texts(shape))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append("Speaker notes: " + notes)
        text = "\n".join(parts).strip()
        if text:
            units.append(("slide", number, text))
    return units, count


def extract_docx(path: Path):
    doc = Document(str(path))
    sections, current = [], []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style is not None else ""
        if style.startswith("Heading") and current:
            sections.append("\n".join(current))
            current = []
        current.append(text)
    if current:
        sections.append("\n".join(current))
    for table in doc.tables:
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        sections.append("\n".join(rows))
    units = [("section", i, s) for i, s in enumerate(sections, start=1)]
    return units, len(units)


def extract_plain(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    sections, current = [], ""
    for para in raw.split("\n\n"):
        if current and len(current) + len(para) > 2000:
            sections.append(current.strip())
            current = ""
        current += para + "\n\n"
    if current.strip():
        sections.append(current.strip())
    units = [("section", i, s) for i, s in enumerate(sections, start=1)]
    return units, len(units)


EXTRACTORS = {
    ".pdf": extract_pdf,
    ".pptx": extract_pptx,
    ".docx": extract_docx,
    ".txt": extract_plain,
    ".md": extract_plain,
}


def extract_file(path: Path, ext: str):
    units, count = EXTRACTORS[ext](path)
    total_chars = sum(len(text) for _, _, text in units)
    if total_chars < MIN_TOTAL_CHARS:
        raise ValueError(
            "Almost no text was found. This may be a scanned file or a file made of pictures. "
            "Scanned file support is planned for a later stage."
        )
    return units, count