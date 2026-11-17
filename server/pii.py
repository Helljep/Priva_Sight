"""
pii.py - the server-side PII validator ("PII rejection").

The extension already redacts everything, and its privacy gate re-checks the
payload. This is the third check: if raw structured PII still reaches the
server, the request is refused with HTTP 422 and nothing is logged or sent
to the model.

The checksums mirror extension/src/pii/validators.js - keep the two in sync.
tests/vectors.json holds shared examples that both languages are tested on.
"""
import re

# ---- Verhoeff (Aadhaar) ----------------------------------------------------
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def verhoeff_valid(num: str) -> bool:
    digits = digits_only(num)
    if not digits:
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(first_digits: str) -> str:
    """Check digit to append to `first_digits` (used by the persona generator)."""
    c = 0
    for i, ch in enumerate(reversed(digits_only(first_digits))):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def luhn_valid(num: str) -> bool:
    d = digits_only(num)
    if not 13 <= len(d) <= 19:
        return False
    total, dbl = 0, False
    for ch in reversed(d):
        n = int(ch)
        if dbl:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        dbl = not dbl
    return total % 10 == 0


def is_aadhaar(s: str) -> bool:
    d = digits_only(s)
    return len(d) == 12 and d[0] in "23456789" and verhoeff_valid(d)


def is_pan(s: str) -> bool:
    return re.fullmatch(r"[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]", s.upper()) is not None


def is_ifsc(s: str) -> bool:
    return re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", s.upper()) is not None


def is_indian_mobile(s: str) -> bool:
    d = digits_only(s)
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return re.fullmatch(r"[6-9]\d{9}", d) is not None


# ---- scanning --------------------------------------------------------------
_TOKEN_RE = re.compile(r"\[[A-Z]+_\d+\]|\{[A-Z_]+\}|\[FACE\]")

_RULES = [
    ("AADHAAR", re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"), is_aadhaar),
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), luhn_valid),
    ("PAN", re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b"), is_pan),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), lambda s: True),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), is_indian_mobile),
    ("IFSC", re.compile(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b"), is_ifsc),
]


def find_pii(text: str) -> list[dict]:
    """Return [{type, sample}] for structured PII left in `text` (tokens ignored)."""
    clean = _TOKEN_RE.sub(" ", text)
    hits, taken = [], []
    for kind, rx, ok in _RULES:
        for m in rx.finditer(clean):
            if not ok(m.group(0)):
                continue
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            hits.append({"type": kind, "sample": _mask(m.group(0))})
    return hits


def _mask(v: str) -> str:
    return "****" if len(v) <= 4 else v[:2] + "*" * min(len(v) - 3, 8) + v[-1]


def collect_strings(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_strings(v, out)
    return out


def scan_payload(payload: dict) -> list[dict]:
    """Scan every string in the request except the screenshot."""
    body = {k: v for k, v in payload.items() if k != "screenshot"}
    hits = []
    for s in collect_strings(body):
        hits.extend(find_pii(s))
    return hits
