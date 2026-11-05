import re
from difflib import get_close_matches

from sqlalchemy import select

from .grading import normalize
from .models import Chunk

PRACTICE_MIN_CONF = 85.0  # Machine-read labels below this are never used in practice
VERY_HIGH_CONF = 95.0     # At or above this, a reading is trusted without lecture support
VARIANT_CUTOFF = 0.8      # Similarity needed to propose a corrected spelling
REVIEW_SECONDS_PER_LABEL = 6  # Updated from your actual test! (50 labels in 5 mins)

def build_vocabulary(db, source_id: int) -> set[str]:
    """Every word (3 letters or more) in the extracted text of one lecture file."""
    texts = db.scalars(select(Chunk.text).where(Chunk.source_id == source_id)).all()
    words: set[str] = set()
    for text in texts:
        words.update(re.findall(r"[^\W\d_]{3,}", normalize(text)))
    return words

def label_words(label: str) -> list[str]:
    return [w for w in normalize(label).split() if len(w) >= 3 and w.isalpha()]

def is_supported(label: str, vocabulary: set[str]) -> bool:
    """Is every word in this label actually found in the lecture text?"""
    words = label_words(label)
    return bool(words) and all(w in vocabulary for w in words)

def region_trust(region, supported: bool) -> str:
    """'high' or 'medium'. Human verified and drawn boxes are always high."""
    if region.status == "verified" or region.origin in ("text", "manual"):
        return "high"
    if region.confidence >= VERY_HIGH_CONF:
        return "high"
    if supported and region.confidence >= PRACTICE_MIN_CONF:
        return "high"
    return "medium"

def accepted_variants(label: str, vocabulary: set[str]) -> list[str]:
    """If a word is missing from the lecture but a near match exists, offer the corrected label."""
    if not vocabulary:
        return []
    pool = sorted(vocabulary)
    fixed, changed = [], False
    for token in normalize(label).split():
        replacement = None
        if len(token) >= 4 and token.isalpha() and token not in vocabulary:
            for candidate in get_close_matches(token, pool, n=3, cutoff=VARIANT_CUTOFF):
                if abs(len(candidate) - len(token)) <= 2:
                    replacement = candidate
                    break
        if replacement:
            fixed.append(replacement)
            changed = True
        else:
            fixed.append(token)
    return [" ".join(fixed)] if changed else []


def is_eligible(region) -> bool:
    """Same rule as the practice query: verified, or machine accepted at or above the cutoff."""
    if region.status == "verified":
        return True
    return region.status == "auto" and region.confidence >= PRACTICE_MIN_CONF