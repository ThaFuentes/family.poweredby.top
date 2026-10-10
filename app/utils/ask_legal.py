"""Local legal list and file. Advice stays with the model.

A person who can open Legal can ask what is already saved, or file a ticket
they just described. "What happens if I ignore it" is not a save.
"""
from __future__ import annotations

import re

_ADVICE = re.compile(
    r"\b(?:what\s+happens|explain|contest|ignore|admit|trouble|probate|whether|"
    r"what\s+does|what\s+do\s+i\s+do)\b",
    re.I,
)
_LIST = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:what(?:'s|\s+is)\s+on\s+(?:my|our|the)\s+legal"
    r"|what\s+legal\s+(?:papers?|records?)"
    r"|(?:show|list|open)\s+(?:me\s+)?(?:my\s+|our\s+|the\s+)?"
    r"(?:legal\s+(?:papers?|records?)|tickets?|citations?)"
    r"|(?:my\s+|our\s+|the\s+)?legal\s+(?:papers?|records?))"
    r"\b",
    re.I,
)
_LOOKUP = re.compile(
    r"\b(?:did\s+i\s+(?:already\s+)?save|have\s+i\s+(?:already\s+)?saved|"
    r"do\s+i\s+already\s+have|already\s+saved)\b",
    re.I,
)
_SAVE_START = re.compile(r"^(?:please\s+)?(?:save|file|add|record)\b", re.I)
_PAPER = re.compile(
    r"\b(?:parking\s+tickets?|fix-?it\s+tickets?|speeding\s+(?:tickets?|citations?)|"
    r"tickets?|citations?|notices?|summons(?:es)?|warnings?|court\s+papers?)\b",
    re.I,
)
_PLACE = re.compile(
    r"\b(?:basket|shopping\s+list|grocery\s+list|fridge|freezer|pantry|inventory)\b",
    re.I,
)
_AMOUNT = re.compile(
    r"\$\s*(\d{1,7}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"|(\d{1,7}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:dollars?|bucks)\b",
    re.I,
)
_DUE = re.compile(
    r"\bdue\s+(?P<when>next\s+\w+|this\s+\w+|tomorrow|today|"
    r"in\s+\d+\s+\w+|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"[A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)",
    re.I,
)
_FROM = re.compile(
    r"\bfrom\s+(?P<who>downtown|the\s+city(?:\s+of\s+[A-Za-z][A-Za-z .'-]{0,40})?|"
    r"[A-Za-z][A-Za-z .'-]{1,60})",
    re.I,
)
_KINDS = (
    (re.compile(r"\bparking\s+tickets?\b", re.I), "ticket", "Parking ticket"),
    (re.compile(r"\bfix-?it\s+tickets?\b", re.I), "ticket", "Fix-it ticket"),
    (re.compile(r"\bspeeding\s+citations?\b", re.I), "citation", "Speeding citation"),
    (re.compile(r"\bspeeding\s+tickets?\b", re.I), "ticket", "Speeding ticket"),
    (re.compile(r"\bcitations?\b", re.I), "citation", "Citation"),
    (re.compile(r"\bnotices?\b", re.I), "notice", "Notice"),
    (re.compile(r"\bsummons(?:es)?\b", re.I), "court", "Summons"),
    (re.compile(r"\bcourt\s+papers?\b", re.I), "court", "Court paper"),
    (re.compile(r"\bwarnings?\b", re.I), "warning", "Warning"),
    (re.compile(r"\btickets?\b", re.I), "ticket", "Ticket"),
)
_STOP = frozenset(
    """
    a an the my our your this that those them it is are was were do did does
    i we you already save saved file filing on in of to for and or paper papers
    legal record records have has
    """.split()
)


def local_legal(text: str):
    """A say-dict, a legal_save tool dict, or None when the model should answer."""
    raw = (text or "").strip()
    if not raw:
        return None
    listing = bool(_LIST.search(raw))
    lookup = bool(_LOOKUP.search(raw))
    saving = _is_save(raw)
    if _ADVICE.search(raw) and not (listing or lookup or saving):
        return None
    if not (listing or lookup or saving):
        return None
    if not _can_legal():
        return {
            "ok": True,
            "say": "Legal papers stay with whoever can open them on the Legal page.",
            "did": [],
            "confirm": False,
            "vault_locked": False,
        }
    if listing:
        return _list_say(raw)
    if lookup:
        return _lookup_say(raw)
    args = legal_save_args(raw)
    if not args:
        return None
    return {"tool": "legal_save", "args": args}


def legal_save_args(text: str) -> dict | None:
    """Parse an explicit file/save sentence. None when it is not a paper."""
    raw = (text or "").strip()
    if not _is_save(raw):
        return None
    kind, title = "other", "Paper"
    for pattern, key, label in _KINDS:
        if pattern.search(raw):
            kind, title = key, label
            break
    args = {"title": title, "kind": kind, "body": raw[:500]}
    amount = _AMOUNT.search(raw)
    if amount:
        args["amount"] = (amount.group(1) or amount.group(2) or "").replace(",", "")
    due = _DUE.search(raw)
    if due:
        from app.utils.ask import _local_day

        day = _local_day(due.group("when"))
        if day:
            args["due"] = day.isoformat()
    who = _FROM.search(raw)
    if who:
        place = re.sub(r"\s+", " ", who.group("who")).strip(" .,")
        if re.search(r"\bdowntown\b", place, re.I):
            args["location"] = "downtown"
        elif place.lower() not in {"the city", "city", "them", "there"}:
            args["agency"] = place[:400]
    return args


def _is_save(raw: str) -> bool:
    if not _SAVE_START.match(raw or ""):
        return False
    if not _PAPER.search(raw):
        return False
    if _PLACE.search(raw):
        return False
    return True


def _can_legal() -> bool:
    try:
        from app.utils.permissions import can

        return bool(can("legal"))
    except Exception:
        return False


def _rows(kind: str | None = None):
    from app.builddb.table_legal_records import LegalRecord
    from app.utils.household import household_id

    qry = LegalRecord.query.filter_by(household_id=household_id())
    if kind:
        qry = qry.filter_by(kind=kind)
    return qry.order_by(LegalRecord.id.desc()).limit(12).all()


def _kind_filter(raw: str) -> str | None:
    if re.search(r"\blegal\b", raw or "", re.I):
        return None
    if re.search(r"\btickets?\b", raw or "", re.I):
        return "ticket"
    if re.search(r"\bcitations?\b", raw or "", re.I):
        return "citation"
    return None


def _money(amount) -> str:
    if amount is None or str(amount).strip() == "":
        return ""
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return ""
    if number == int(number):
        return f"${int(number)}"
    return f"${number:.2f}"


def _line(row) -> str:
    bits = [str(row.title or "Paper")]
    if row.agency:
        bits.append(str(row.agency))
    money = _money(row.amount)
    if money:
        bits.append(money)
    bits.append(f"/legal/{row.id}")
    return " · ".join(bits)


def _say(text: str) -> dict:
    return {
        "ok": True,
        "say": text,
        "did": [],
        "confirm": False,
        "vault_locked": False,
    }


def _list_say(raw: str) -> dict:
    rows = _rows(_kind_filter(raw))
    if not rows:
        return _say("No legal papers saved yet.")
    lines = "\n".join(f"· {_line(row)}" for row in rows)
    return _say("Legal papers:\n" + lines)


def _lookup_say(raw: str) -> dict:
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]+", (raw or "").lower())
        if tok not in _STOP and len(tok) > 2
    ]
    rows = _rows()
    hits = []
    for row in rows:
        blob = " ".join(
            str(part or "")
            for part in (row.title, row.agency, row.body, row.kind, row.location)
        ).lower()
        if tokens and all(tok in blob for tok in tokens):
            hits.append(row)
    if not hits:
        return _say("I don't see that on the legal papers.")
    lines = "\n".join(f"· {_line(row)}" for row in hits[:8])
    return _say("Already saved:\n" + lines)


def _trim(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _cases(hid: int):
    from app.builddb.table_legal_cases import LegalCase

    return LegalCase.query.filter_by(household_id=hid).order_by(LegalCase.id.desc()).all()


def _one_case(hid: int, args: dict):
    from app.utils.crypto import decrypt_text

    raw_id = args.get("id") or args.get("case_id")
    if str(raw_id or "").isdigit():
        for row in _cases(hid):
            if int(row.id) == int(raw_id):
                return row, None
        return None, {"ok": False, "error": "No case with that id in this house."}
    needle = _trim(args.get("q") or args.get("name") or "", 200).lower()
    if not needle:
        return None, {"ok": False, "need": ["id"], "hint": "Which case? Give the id or the title."}
    hits = []
    for row in _cases(hid):
        title = (decrypt_text(row.title) or "").lower()
        number = str(row.number or "")
        if needle in title or needle in f"case #{number}" or needle == number:
            hits.append(row)
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, {"ok": False, "error": f"No case matches {needle}."}
    from app.builddb.table_legal_cases import case_label

    return None, {
        "ok": False,
        "need": ["id"],
        "choices": [case_label(row) for row in hits[:8]],
        "hint": "Which case? " + ", ".join(case_label(row) for row in hits[:6]),
    }


def tool_case_save(args: dict | None = None) -> dict:
    """Open a case, update it, add a follow-up, or tie a paper to it."""
    args = args if isinstance(args, dict) else {}
    if not _can_legal():
        return {"ok": False, "error": "You cannot change legal records."}
    from app.builddb.builddb import db
    from app.builddb.table_legal_cases import case_label
    from app.builddb.table_legal_records import LegalRecord
    from app.services.legal import add_followup, edit_case, open_case
    from app.utils.crypto import decrypt_text
    from app.utils.household import household_id
    from flask_login import current_user

    hid = household_id()
    action = _trim(args.get("action") or "open", 20).lower()
    if action in ("add", "new", "create", ""):
        action = "open"
    if action in ("edit", "patch", "close"):
        action = "update"
    if action in ("note", "link", "email"):
        args = {**args, "kind": action}
        action = "followup"
    if action == "tie":
        action = "attach"

    if action == "open":
        title = _trim(args.get("title") or args.get("name"), 500)
        case, err = open_case(
            hid=hid,
            user_id=getattr(current_user, "id", None),
            title=title,
            summary=_trim(args.get("summary") or args.get("body"), 8000) or None,
        )
        if err:
            return {"ok": False, "need": ["title"], "hint": err}
        record_id = args.get("record_id")
        if str(record_id or "").isdigit():
            rec = LegalRecord.query.filter_by(id=int(record_id), household_id=hid).first()
            if rec is not None and not rec.case_id:
                rec.case_id = case.id
        db.session.commit()
        return {
            "ok": True,
            "id": case.id,
            "label": case_label(case),
            "title": decrypt_text(case.title) or title,
            "status": case.status,
            "href": f"/legal/cases/{case.id}",
            "did": "opened",
        }

    case, err = _one_case(hid, args)
    if err:
        return err
    if action == "update":
        fields = {}
        if args.get("title") or args.get("name"):
            fields["title"] = _trim(args.get("title") or args.get("name"), 500)
        if args.get("status"):
            fields["status"] = _trim(args.get("status"), 20)
        if "summary" in args or "body" in args:
            fields["summary"] = _trim(args.get("summary") if "summary" in args else args.get("body"), 8000)
        edit_case(case, fields)
        db.session.commit()
        return {
            "ok": True,
            "id": case.id,
            "label": case_label(case),
            "title": decrypt_text(case.title) or "",
            "status": case.status,
            "href": f"/legal/cases/{case.id}",
            "did": "updated",
        }
    if action == "followup":
        kind = _trim(args.get("kind") or "note", 20).lower()
        if kind == "file":
            return {
                "ok": False,
                "error": "Add that photo on the paper with legal_save, action update, and the record id or title.",
            }
        fu, ferr = add_followup(
            case,
            user_id=getattr(current_user, "id", None),
            kind=kind,
            title=_trim(args.get("title") or args.get("note"), 500),
            body=_trim(args.get("body") or args.get("notes"), 8000),
            url=_trim(args.get("url") or args.get("link"), 2000),
            email_from=_trim(args.get("email_from"), 200),
        )
        if ferr:
            return {"ok": False, "need": ["body"], "hint": ferr}
        db.session.commit()
        return {
            "ok": True,
            "id": case.id,
            "followup_id": fu.id,
            "kind": fu.kind,
            "label": case_label(case),
            "href": f"/legal/cases/{case.id}",
            "did": "follow-up saved",
        }
    if action == "attach":
        raw = args.get("record_id") or args.get("paper_id")
        if not str(raw or "").isdigit():
            return {"ok": False, "need": ["record_id"], "hint": "Which paper? I need the record id."}
        rec = LegalRecord.query.filter_by(id=int(raw), household_id=hid).first()
        if rec is None:
            return {"ok": False, "error": "That paper is not in this house."}
        rec.case_id = case.id
        db.session.commit()
        return {
            "ok": True,
            "id": case.id,
            "record_id": rec.id,
            "label": case_label(case),
            "href": f"/legal/cases/{case.id}",
            "did": "paper tied to the case",
        }
    return {"ok": False, "error": "action is open, update, followup, or attach."}
