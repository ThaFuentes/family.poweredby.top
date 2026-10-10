"""One Ask message can ask for several things. Split those requests apart.

A shopping list stays one request ("milk, eggs, and bread"). A second job
in the same message — a new sentence, another line, "and remind me" —
becomes its own request so the first match cannot swallow the rest.

"and tell me what oil it needs" stays with the machine. "and tell me what
to bring" does not. A stock sentence stays whole unless a real second
question is hanging off it ("and while you do that, explain…").
"""
from __future__ import annotations

import re

# A new chore. "and tell me" / "and make sure" stay with the first request.
_ACTION = (
    r"(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:also\s+)?"
    r"(?:add|put|remind|set|save|write|note|remember|mark|remove|delete|"
    r"log|start|end|move|schedule|we\s+need|i\s+need)"
)
# A new sentence may also be a question. "file" is a legal paper, not a chore verb.
_NEXT = (
    _ACTION
    + r"|(?:please\s+)?(?:show|list|tell|what(?:'s|\s+is)?|where|when|who|why|how|"
    r"check|look|open|make|change|file)"
)

_HARD = re.compile(r"\n+|;\s+|(?:^|\s)\d{1,2}[\.\)]\s+")
_AND_THEN = re.compile(r"\s+(?:and then|then|also|plus)\s+", re.I)
_AND_COMMAND = re.compile(r"\s+and\s+(?=(?:" + _ACTION + r")\b)", re.I)
# A second question. "tell me what oil it needs" and "tell me the first thing"
# stay with the sentence in front. "tell me what to bring" does not.
_AND_ASIDE = re.compile(
    r"\s+and\s+(?=(?:while|whether|explain|what(?:'s|\s+is))\b|"
    r"tell\s+me\s+(?!what\s+(?:oil|fluid|spec|it)\b)(?!the\s+first\s+thing\b))",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.?!])\s+(?=(?:" + _NEXT + r")\b)", re.I)
_COMMA_COMMAND = re.compile(r",\s+(?:and\s+)?(?=(?:" + _ACTION + r")\b)", re.I)
_COMMA_TALK = re.compile(
    r",\s+and\s+(?=(?:did|do|what|whether|tell|explain)\b)",
    re.I,
)
_LEAD = re.compile(
    r"^(?:(?:and|also|then|plus|oh)\s+|"
    r"(?:(?:two|three|four)\s+things|a couple(?:\s+of)?\s+things)[:,]?\s+)",
    re.I,
)
_NOISE = re.compile(
    r"^(?:oh|um+|uh+|er+|hmm+|hey|hi|hello|yo|ok(?:ay)?|alright|so|well|yeah|yep|please)[.!?]*$",
    re.I,
)
_ORDINAL = re.compile(r"\b(?:first|second|third|fourth)\b", re.I)
_JUST = re.compile(r"^just\s+", re.I)


def split_requests(text: str) -> list[str]:
    """Return 1–8 requests. One ordinary sentence stays a single-item list."""
    raw = (text or "").strip()
    if not raw:
        return []
    from app.utils.ask_basket_language import basket_add_args
    from app.utils.ask_plain import plain_talk

    ordinal = _ordinal_pieces(raw)
    if ordinal:
        parts = ordinal
    else:
        # "we're out of milk, add it to the basket" is one shopping add, not a discard.
        plain = plain_talk(raw)
        second = _has_second_talk(raw)
        if (
            plain
            and plain.lower() != raw.lower()
            and basket_add_args(plain)
            and not second
        ):
            return [plain]
        if basket_add_args(raw) and not second:
            return [raw]
        # One inventory sentence can already name several moves and counts.
        # A hanging question ("and while you do that, explain") is not part of that move.
        if not second:
            try:
                from app.utils.ask import _parse_stock_jobs

                if _parse_stock_jobs(raw):
                    return [raw]
            except Exception:
                pass
        parts = [raw]
    for pattern in (
        _HARD,
        _AND_THEN,
        _AND_COMMAND,
        _AND_ASIDE,
        _SENTENCE,
        _COMMA_COMMAND,
        _COMMA_TALK,
    ):
        nxt = []
        for part in parts:
            nxt.extend(_cut(part, pattern))
        parts = nxt
    out = []
    for part in parts:
        piece = part.strip(" \t,")
        while True:
            nxt = _LEAD.sub("", piece).strip()
            if nxt == piece:
                break
            piece = nxt
        if piece and not _NOISE.match(piece):
            out.append(piece)
    if not out:
        return [raw]
    if len(out) > 8:
        out = out[:7] + [" ".join(out[7:])]
    return out


def _has_second_talk(text: str) -> bool:
    return bool(_AND_ASIDE.search(text or "") or _COMMA_TALK.search(text or ""))


def _ordinal_pieces(text: str) -> list[str] | None:
    """first / second / third only when they actually number more than one job."""
    marks = list(_ORDINAL.finditer(text or ""))
    if len(marks) < 2:
        return None
    pieces = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = text[mark.end():end].strip(" \t,.;:")
        chunk = _JUST.sub("", chunk).strip()
        if chunk:
            pieces.append(chunk)
    return pieces or None


def _cut(part: str, pattern: re.Pattern) -> list[str]:
    from app.utils.ask_basket_language import basket_add_args

    if basket_add_args(part):
        return [part]
    bits = [bit for bit in pattern.split(part) if bit and bit.strip()]
    return bits or [part]
