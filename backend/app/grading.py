import re
import unicodedata
from difflib import SequenceMatcher

ARTICLES = ("the ", "a ", "an ")
CLOSE_MIN_LENGTH = 8
CLOSE_MIN_RATIO = 0.9

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\W_]+", " ", text.lower()).strip()
    for article in ARTICLES:
        if text.startswith(article):
            text = text[len(article):]
    return text

def grade_answer(student: str, accepted: list[str]) -> str:
    answer = normalize(student)
    if not answer:
        return "blank"
    keys = [k for k in (normalize(a) for a in accepted) if k]
    if answer in keys:
        return "exact"
    for key in keys:
        if len(key) >= CLOSE_MIN_LENGTH and len(answer) >= CLOSE_MIN_LENGTH:
            if SequenceMatcher(None, answer, key).ratio() >= CLOSE_MIN_RATIO:
                return "close"
    return "wrong"

def outcome_points(outcome: str) -> float:
    return 1.0 if outcome in ("exact", "close") else 0.0