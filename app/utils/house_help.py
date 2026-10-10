"""Plain help for the household. The Help page and Ask both read this.

No keys, no vault secrets, and no orders for the model. Ask quotes a short
answer only when the words are about the app itself.
"""
from __future__ import annotations

import re

OVERVIEW = (
    "Help is a page in this app, at Help in the side list and under More. "
    "It covers AI keys, bot keys, Happened, and the vault. "
    "Ask can answer from that page without an AI key."
)

KEYS = (
    "A household leader adds the AI key. Open Household, then AI keys. "
    "Copy a key from Groq, Gemini, Grok, or OpenAI and add it. "
    "A new key does not replace one you already saved. "
    "Leave Replace blank to keep the saved key, pick the model, and press Save model. "
    "Main is the key Ask tries first. Press Test the main key before you leave. "
    "Everyday is lists and short chat. Heavy is photos and oil lookup. "
    "The full steps are on the Help page."
)

BOT = (
    "A bot key is not the AI key. A leader opens that person and uses What this key can do. "
    "The key can only do what that person's role can already do. "
    "A vault key can read cards that person can see. It cannot change the house. "
    "There is no delete on the bot API. "
    "The full steps are on the Help page."
)

UNDO = (
    "Happened is the put-back list, for leaders. It shows scans, basket taps, parts, "
    "removed items, and what a bot or Maya changed. Press Put back once. "
    "A new item is put away. An edit goes back to the old words. "
    "A note, basket line, reminder, log, or file the bot added goes to the recycle bin. "
    "A replaced file goes back to the copy that was archived. "
    "A mileage or hour reading goes back with its log. "
    "A sent email and a vault look-up stay as they are. Children do not open Happened. "
    "The full steps are on the Help page."
)

MAP = (
    "The security map is the site owner's desk. Households do not open it, "
    "and it does not show vault cards or AI keys. "
    "The full note is on the Help page."
)

VAULT = (
    "Passwords stay on the Vault page. Ask can open a card after the app password. "
    "Adding or changing a card stays on that page. Children do not open the vault. "
    "The full note is on the Help page."
)

SECTIONS = (
    ("Start here", OVERVIEW),
    ("AI keys", KEYS),
    ("Bot keys", BOT),
    ("Put back", UNDO),
    ("Vault", VAULT),
    ("Security map", MAP),
)


def page_sections() -> list[tuple[str, str]]:
    return list(SECTIONS)


_FULL = re.compile(
    r"^(?:please\s+)?(?:help|support|i need help|where(?:'s| is) (?:the )?(?:help|support))[.!?]*$",
    re.I,
)
_KEY = re.compile(
    r"\b(?:api|ai|groq|gemini|openai|grok)\s+keys?\b|\b(?:add|paste|save|use|replace)\b.{0,40}\b(?:api|ai)\s+key\b",
    re.I,
)
_BOT = re.compile(r"\bbot\s+keys?\b|what this key can do", re.I)
_UNDO = re.compile(
    r"\bhappened\b|\bput\s+back\b|\bhow do i undo\b|\bundo\b.{0,24}\b(?:bot|maya)\b",
    re.I,
)
_MAP = re.compile(r"\b(?:threat|security)\s+map\b", re.I)
_VAULT = re.compile(r"\bhow do i\b.{0,40}\bvault\b", re.I)


def local_help_say(text: str) -> str | None:
    """A short answer when the words are about the app. Oil, stock, and chores miss."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw or len(raw) > 240:
        return None
    if _FULL.match(raw):
        return OVERVIEW
    if _KEY.search(raw):
        return KEYS
    if _BOT.search(raw):
        return BOT
    if _MAP.search(raw):
        return MAP
    if _VAULT.search(raw):
        return VAULT
    if _UNDO.search(raw):
        return UNDO
    return None
