from .ai_ocr import read_labels_with_ai
from .trust import build_vocabulary, accepted_variants
import re
import shutil
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output
from sqlalchemy import delete, select

from .config import settings
from .models import LabelRegion, PageRender

UPSCALE = 2.0
MIN_CONF_KEEP = 40.0
MIN_CONF_AUTO = 70.0
MAX_LABEL_CHARS = 60
MAX_LABEL_WORDS = 7
MIN_ALPHA_RATIO = 0.6
MIN_LINE_HEIGHT = 8
MAX_LINE_FRACTION = 0.15
MERGE_GAP = 0.3
PAD = 0.003
NOISE = re.compile(r"^(fig(ure)?|table|slide|page|source|references?|copyright)\b", re.IGNORECASE)

class OcrUnavailable(Exception):
    pass

def _configure() -> None:
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        return
    if shutil.which("tesseract"):
        return
    windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if windows_default.exists():
        pytesseract.pytesseract.tesseract_cmd = str(windows_default)
        return
    raise OcrUnavailable("Tesseract is not installed or was not found. Install it, or set TESSERACT_CMD in the .env file.")

def _read_lines(img: Image.Image) -> list[dict]:
    data = pytesseract.image_to_data(img, config="--psm 11", output_type=Output.DICT)
    groups: dict = {}
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if conf < 0:
            continue
        left, top = data["left"][i], data["top"][i]
        right, bottom = left + data["width"][i], top + data["height"][i]
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        group = groups.get(key)
        if group is None:
            groups[key] = {"words": [(left, text)], "x0": left, "y0": top, "x1": right, "y1": bottom, "confs": [conf]}
        else:
            group["words"].append((left, text))
            group["x0"] = min(group["x0"], left)
            group["y0"] = min(group["y0"], top)
            group["x1"] = max(group["x1"], right)
            group["y1"] = max(group["y1"], bottom)
            group["confs"].append(conf)

    lines = []
    for group in groups.values():
        group["words"].sort()
        lines.append({
            "x0": group["x0"],
            "y0": group["y0"],
            "x1": group["x1"],
            "y1": group["y1"],
            "text": " ".join(word for _, word in group["words"]),
            "conf": sum(group["confs"]) / len(group["confs"]),
        })
    return lines

def _clean(text: str) -> str:
    text = " ".join(text.split())
    return text.strip(" .,;:|_-~'\"`()[]{}<>*")

def _plausible(text: str) -> bool:
    if len(text) < 2 or len(text) > MAX_LABEL_CHARS:
        return False
    if len(text.split()) > MAX_LABEL_WORDS:
        return False
    letters = sum(ch.isalpha() for ch in text)
    compact = len(text.replace(" ", ""))
    if letters < 2 or letters / compact < MIN_ALPHA_RATIO:
        return False
    if NOISE.match(text):
        return False
    return True

def _center_inside(box: dict, other: dict) -> bool:
    cx = (box["x0"] + box["x1"]) / 2
    cy = (box["y0"] + box["y1"]) / 2
    return other["x0"] <= cx <= other["x1"] and other["y0"] <= cy <= other["y1"]

def _dedupe(lines: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for line in sorted(lines, key=lambda item: -item["conf"]):
        if any(_center_inside(line, k) or _center_inside(k, line) for k in kept):
            continue
        kept.append(line)
    return kept

def _merge_lines(lines: list[dict]) -> list[dict]:
    lines = sorted(lines, key=lambda item: (item["y0"], item["x0"]))
    changed = True
    while changed:
        changed = False
        for i in range(len(lines)):
            for j in range(len(lines)):
                if i == j:
                    continue
                a, b = lines[i], lines[j]
                height = max(a["y1"] - a["y0"], b["y1"] - b["y0"])
                gap = b["y0"] - a["y1"]
                overlap = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
                narrow = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
                if 0 <= gap < MERGE_GAP * height and overlap > 0.4 * narrow:
                    lines[i] = {
                        "x0": min(a["x0"], b["x0"]),
                        "y0": min(a["y0"], b["y0"]),
                        "x1": max(a["x1"], b["x1"]),
                        "y1": max(a["y1"], b["y1"]),
                        "text": a["text"] + " " + b["text"],
                        "conf": min(a["conf"], b["conf"]),
                    }
                    del lines[j]
                    changed = True
                    break
            if changed:
                break
    return lines

def read_labels(image: Image.Image) -> list[dict]:
    _configure()
    width, height = image.size
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    big = gray.resize((int(width * UPSCALE), int(height * UPSCALE)), Image.Resampling.LANCZOS)

    raw_lines: list[dict] = []
    try:
        for version in (big, ImageOps.invert(big)):
            raw_lines.extend(_read_lines(version))
    except pytesseract.TesseractNotFoundError:
        raise OcrUnavailable("Tesseract could not be started. Check the installation path.")

    candidates = []
    for line in raw_lines:
        line_height = (line["y1"] - line["y0"]) / UPSCALE
        if line_height < MIN_LINE_HEIGHT or line_height > height * MAX_LINE_FRACTION:
            continue
        text = _clean(line["text"])
        if line["conf"] >= MIN_CONF_KEEP and _plausible(text):
            line["text"] = text
            candidates.append(line)

    merged = _merge_lines(_dedupe(candidates))

    labels = []
    for line in merged:
        if not _plausible(line["text"]):
            continue
        labels.append({
            "x0": max(0.0, line["x0"] / UPSCALE / width - PAD),
            "y0": max(0.0, line["y0"] / UPSCALE / height - PAD),
            "x1": min(1.0, line["x1"] / UPSCALE / width + PAD),
            "y1": min(1.0, line["y1"] / UPSCALE / height + PAD),
            "text": line["text"],
            "confidence": round(line["conf"], 1),
        })
    return labels

def ocr_page_regions(db, page: PageRender) -> int:
    image = Image.open(page.file_path).convert("RGB")
    found = read_labels_with_ai(page.file_path)


    vocabulary = build_vocabulary(db, page.source_id)
    db.execute(
        delete(LabelRegion).where(
            LabelRegion.page_id == page.id,
            LabelRegion.origin == "ocr",
            LabelRegion.status.in_(["auto", "proposed"]),
        )
    )
    existing = db.scalars(select(LabelRegion).where(LabelRegion.page_id == page.id)).all()

    created = 0
    for item in found:
        cx = (item["x0"] + item["x1"]) / 2
        cy = (item["y0"] + item["y1"]) / 2
        if any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in existing):
            continue
            
        # Filter out non-diagram labels
        if item.get("role") != "diagram_label":
            reject_reason = "role"
        elif len(item["text"].split()) > 5 or len(item["text"]) > 40:
            reject_reason = "length"
        else:
            reject_reason = None
            
        if reject_reason:
            # Save it as rejected so we can audit it
            db.add(LabelRegion(
                page_id=page.id, user_id=page.user_id,
                x0=item["x0"], y0=item["y0"], x1=item["x1"], y1=item["y1"],
                text=item["text"], origin="ocr", status="rejected",
                confidence=100.0, reject_reason=reject_reason, role=item.get("role")
            ))
            continue
            
        db.add(
            LabelRegion(
                page_id=page.id,
                user_id=page.user_id,
                x0=item["x0"],
                y0=item["y0"],
                x1=item["x1"],
                y1=item["y1"],
                text=item["text"],
                origin="ocr",
                status="auto",
                confidence=100.0,
                role=item.get("role")
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