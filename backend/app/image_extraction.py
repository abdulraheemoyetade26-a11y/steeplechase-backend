import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .config import settings
from .extraction import _shape_texts
from .models import ImageItem

MIN_SIDE = 120
MIN_AREA = 20000
MIN_BYTES = 3000
MAX_DIMENSION = 2000
REPEAT_LIMIT = 3


@dataclass
class Candidate:
    location_type: str
    location_number: int
    data: bytes
    ext: str
    width: int
    height: int
    digest: str
    title: str
    context: str


def _normalize(raw: bytes, crop=None):
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return None

    if crop:
        w, h = img.size
        left, top, right, bottom = crop
        box = (int(w * left), int(h * top), int(w * (1 - right)), int(h * (1 - bottom)))
        if box[2] - box[0] > 10 and box[3] - box[1] > 10:
            img = img.crop(box)

    w, h = img.size
    if min(w, h) < MIN_SIDE or w * h < MIN_AREA:
        return None

    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)

    buffer = io.BytesIO()
    if has_alpha:
        img.convert("RGBA").save(buffer, format="PNG")
        ext = "png"
    else:
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
        ext = "jpg"

    data = buffer.getvalue()
    if len(data) < MIN_BYTES:
        return None
    return data, ext, img.size[0], img.size[1]


def _make_candidate(location_type, number, normalized, title, context):
    data, ext, width, height = normalized
    return Candidate(
        location_type=location_type,
        location_number=number,
        data=data,
        ext=ext,
        width=width,
        height=height,
        digest=hashlib.sha1(data).hexdigest(),
        title=title,
        context=context,
    )


def _pdf_candidates(path: Path) -> list[Candidate]:
    found = []
    with fitz.open(path) as doc:
        for number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            title = text.split("\n")[0].strip()[:200] if text else ""
            context = text[:400]
            for info in page.get_images(full=True):
                xref, smask = info[0], info[1]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if smask and not pix.alpha:
                        pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
                    raw = pix.tobytes("png")
                except Exception:
                    continue
                normalized = _normalize(raw)
                if normalized:
                    found.append(_make_candidate("page", number, normalized, title, context))
    return found


def _picture_shapes(shape):
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for inner in shape.shapes:
            yield from _picture_shapes(inner)
    else:
        try:
            shape.image
        except Exception:
            return
        yield shape


def _pptx_candidates(path: Path) -> list[Candidate]:
    found = []
    prs = Presentation(str(path))
    for number, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            texts.extend(_shape_texts(shape))
        context = "\n".join(texts)[:400]

        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text_frame.text.strip()
        except Exception:
            title = ""
        if not title and texts:
            title = texts[0].split("\n")[0].strip()
        title = title[:200]

        for top_shape in slide.shapes:
            for pic in _picture_shapes(top_shape):
                try:
                    raw = pic.image.blob
                    crop = (
                        getattr(pic, "crop_left", 0) or 0,
                        getattr(pic, "crop_top", 0) or 0,
                        getattr(pic, "crop_right", 0) or 0,
                        getattr(pic, "crop_bottom", 0) or 0,
                    )
                except Exception:
                    continue
                normalized = _normalize(raw, crop if any(crop) else None)
                if normalized:
                    found.append(_make_candidate("slide", number, normalized, title, context))
    return found


def extract_images(path: Path, ext: str) -> list[Candidate]:
    if ext == ".pdf":
        candidates = _pdf_candidates(path)
    elif ext == ".pptx":
        candidates = _pptx_candidates(path)
    else:
        return []

    places = defaultdict(set)
    for c in candidates:
        places[c.digest].add((c.location_type, c.location_number))
    return [c for c in candidates if len(places[c.digest]) < REPEAT_LIMIT]


def store_images(db, source, ext: str) -> int:
    candidates = extract_images(Path(source.stored_path), ext)
    out_dir = Path(settings.upload_dir) / str(source.user_id) / "images" / str(source.id)
    out_dir.mkdir(parents=True, exist_ok=True)

    for order, c in enumerate(candidates):
        file_path = out_dir / f"{order:04d}.{c.ext}"
        file_path.write_bytes(c.data)
        db.add(
            ImageItem(
                source_id=source.id,
                user_id=source.user_id,
                order_index=order,
                location_type=c.location_type,
                location_number=c.location_number,
                file_path=str(file_path),
                width=c.width,
                height=c.height,
                content_hash=c.digest,
                context_text=c.context,
                suggested_label=c.title,
            )
        )
    return len(candidates)