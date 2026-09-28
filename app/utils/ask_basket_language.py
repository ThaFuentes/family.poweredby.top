"""Natural-language basket phrases kept separate from the large Ask router."""
from __future__ import annotations

import re


def basket_add_args(text: str) -> dict | None:
    """Return basket_add args for explicit, conversational add requests only."""
    raw = (text or "").strip()
    match = re.match(
        r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:i(?:'d| would)?\s+like\s+you\s+to\s+)?"
        r"(?:add|put|need|we need|pick up|grab)\s+(?P<items>.+?)\s+"
        r"(?:to|on|onto|in|for)\s+(?:my\s+|our\s+|the\s+)?"
        r"(?:shopping\s+(?:list|basket)|basket|grocery\s+list|list)"
        r"(?:\s+from\s+(?P<store>.+?))?"
        r"(?:[, ]+(?:please|thanks|thank you))?[.!?]*$",
        raw,
        re.I,
    )
    if not match:
        return None

    names_text = match.group("items")
    store = (match.group("store") or "").strip(" .,!?:;")
    if not store:
        from_store = re.search(r"\s+from\s+(.+)$", names_text, re.I)
        if from_store:
            store = from_store.group(1).strip(" .,!?:;")
            names_text = names_text[:from_store.start()]
    names = [
        re.sub(r"\s+", " ", part).strip(" .,!?:;")
        for part in re.split(r"\s*(?:,|;|\band\b|\balso\b)\s*", names_text, flags=re.I)
    ]
    names = [re.sub(r"^(?:the|my|our|a|an)\s+", "", name, flags=re.I) for name in names if name]
    names = [re.sub(r"\s+(?:please|thanks|thank you)$", "", name, flags=re.I).strip() for name in names]
    names = [name[:200] for name in names if name]
    if not names:
        return None
    args = {"names": names}
    if store:
        args["store"] = store[:120]
    return args


def basket_remove_args(text: str) -> dict | None:
    raw = (text or "").strip()
    match = re.match(
        r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:remove|delete|take\s+off|cross\s+off|cross\s+out)\s+(?P<name>.+?)\s+"
        r"(?:from|off)\s+(?:my\s+|our\s+|the\s+)?"
        r"(?:shopping\s+(?:list|basket)|basket|grocery\s+list|list)"
        r"(?:[, ]+(?:please|thanks|thank you))?[.!?]*$",
        raw,
        re.I,
    )
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip(" .,!?:;")
    name = re.sub(r"^(?:the|my|our|a|an)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(?:please|thanks|thank you)$", "", name, flags=re.I).strip()
    return {"q": name[:200]} if name else None


def basket_list_request(text: str) -> bool:
    raw = (text or "").strip()
    patterns = (
        r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
        r"(?:show(?:\s+me)?|list|tell\s+me)\s+(?:what(?:'s|\s+is)\s+)?"
        r"(?:(?:on|in)\s+)?(?:(?:my|our|the)\s+)?"
        r"(?:basket|shopping\s+list|grocery\s+list|list)"
        r"(?:[, ]+(?:please|thanks|thank you))?[?!.]*$",
        r"^what(?:'s|\s+is)\s+(?:on|in)\s+(?:(?:my|our|the)\s+)?"
        r"(?:shopping\s+list|basket|grocery\s+list|list)[?!.]*$",
    )
    return any(re.match(pattern, raw, re.I) for pattern in patterns)
