"""Simpler wording for casual household talk.

The first pass uses the words they typed. If that misses, or the model says
it does not understand, Ask tries this wording once and then asks again.
"""
from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")
_LEAD = re.compile(
    r"^(?:(?:um+|uh+|er+|hmm+|hey|hi|hello|yo|ok(?:ay)?|alright|all right|so|well|yeah|yep|yup|please|sorry)\b[\s,!]*)+",
    re.I,
)
_POLITE = re.compile(
    r"^(?:"
    r"would\s+you\s+mind\s+"
    r"|do\s+you\s+mind\s+"
    r"|(?:can|could|would)\s+you\s+(?:please\s+|just\s+)?"
    r"|i\s+need\s+you\s+to\s+"
    r"|i(?:'d| would)\s+like\s+you\s+to\s+"
    r"|go\s+ahead\s+and\s+"
    r"|(?:let's|lets)\s+"
    r"|please\s+"
    r")",
    re.I,
)
_TAIL = re.compile(
    r"(?:\s*,?\s*(?:please|thanks|thank you|real quick|for me|right quick|"
    r"when you get a (?:sec|second|minute)|if you (?:can|could|don't mind)))+[.!?]*$",
    re.I,
)
# "cross the oat milk off the list if it's on there" is still a remove.
_IF_ON = re.compile(
    r"(?:\s*,?\s*if\s+(?:it(?:'s| is)|they(?:'re| are))\s+"
    r"(?:on there|there|you see it|we have it))+[.!?]*$",
    re.I,
)
_FORGET = re.compile(r"^(?:don'?t|do not)\s+let\s+me\s+forget\s+(?:to|about)\s+", re.I)
_JUST = re.compile(r"^(?:just|maybe|please)\s+", re.I)
_ADDING = re.compile(r"^adding\s+", re.I)
# "remind me the filter" is a reminder. "remind me what that was" is a question.
_REMIND_THAT = re.compile(
    r"^remind me\s+(?!to\b|about\b|that\b|what\b|who\b|when\b|where\b|why\b|how\b|which\b)",
    re.I,
)
_OUT_THEN_ADD = re.compile(
    r"^(?:we(?:'re| are)|i(?:'m| am)|we|i)\s+(?:all\s+)?out\s+of\s+(?P<item>.+?)\s*,\s*"
    r"(?:so\s+)?(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?add\s+(?:it|that|some|them)?\s*"
    r"(?:to|on|onto)\s+(?:my\s+|our\s+|the\s+)?(?:shopping\s+(?:list|basket)|basket|grocery\s+list|list)\b",
    re.I,
)
_ONTO_LIST = re.compile(
    r"^(?:stick|toss|throw|chuck)\s+(?P<items>.+?)\s+(?:on|onto|to|in)\s+(?:my\s+|our\s+|the\s+)?"
    r"(?:shopping\s+(?:list|basket)|grocery\s+list|basket|list)\b",
    re.I,
)
_STORE = re.compile(r"^what\s+do\s+we\s+need\s+from\s+the\s+store\b", re.I)
_CONFUSED = re.compile(
    r"\b(?:don'?t understand|do not understand|not sure what you|didn'?t catch|did not catch|"
    r"didn'?t get that|rephrase|say that again|what do you mean|can you clarify|i'?m confused)\b",
    re.I,
)
_BUSY = re.compile(
    r"busy|timed out|could not reach|request failed|too many|high demand|overloaded|try again later",
    re.I,
)


def plain_talk(text: str) -> str:
    """Drop filler so a casual sentence can hit the household commands."""
    raw = _SPACE.sub(" ", (text or "").strip())
    if not raw:
        return ""
    cleaned = _LEAD.sub("", raw).strip()
    cleaned = _POLITE.sub("", cleaned).strip()
    cleaned = _TAIL.sub("", cleaned).strip(" .,!?:;")
    cleaned = _IF_ON.sub("", cleaned).strip(" .,!?:;")
    cleaned = _JUST.sub("", cleaned).strip()
    cleaned = _ADDING.sub("add ", cleaned)
    cleaned = _FORGET.sub("remind me to ", cleaned)
    cleaned = _REMIND_THAT.sub("remind me that ", cleaned)
    out_of = _OUT_THEN_ADD.match(cleaned)
    if out_of:
        item = re.sub(r"^(?:the|some|any)\s+", "", out_of.group("item").strip(" .,!?:;"), flags=re.I)
        return f"add {item} to the basket" if item else cleaned
    onto = _ONTO_LIST.match(cleaned)
    if onto:
        items = onto.group("items").strip(" .,!?:;")
        return f"add {items} to the basket" if items else cleaned
    if _STORE.match(cleaned):
        return "what's on the shopping list"
    return cleaned


def talk_attempts(text: str) -> list[str]:
    """Original wording, then the simpler line when it actually changed."""
    raw = _SPACE.sub(" ", (text or "").strip())
    if not raw:
        return []
    plain = plain_talk(raw)
    if plain and plain.lower() != raw.lower():
        return [raw, plain]
    return [raw]


def sounds_confused(say: str) -> bool:
    """A short reply that admits it missed, not a real answer that mentions the phrase."""
    text = (say or "").strip()
    if not text or len(text) > 160 or not _CONFUSED.search(text):
        return False
    extra = _CONFUSED.sub(" ", text)
    extra = re.sub(r"[^A-Za-z0-9]+", " ", extra).strip()
    return len(extra.split()) <= 8


def model_is_busy(raw: str) -> bool:
    return bool(_BUSY.search(raw or ""))
