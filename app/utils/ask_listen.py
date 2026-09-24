"""Ask must hear the turn before it touches inventory or vehicles."""

LISTEN_RULES = """
Listen to this turn. Do not assume inventory or vehicles.
- A command to put/move something is not a new item. Find the saved food. Never create a grocery whose name is the whole sentence.
- Do not call house (dump inventory, vehicles, tools, basket) unless they asked to show, list, or open that.
- Do not create a grocery, tool, or vehicle unless they clearly asked to add a new named product (“add peanut butter”, “save this drill”).
- If you are not sure whether they mean food, a tool, or a truck, ask one short question. Do not guess a list.
- find / item_inspect the named thing first.
"""


def is_move_or_count(text: str) -> bool:
    from app.utils.ask import _parse_stock_jobs, _looks_like_command

    raw = (text or "").strip()
    if not raw:
        return False
    if _parse_stock_jobs(raw):
        return True
    return _looks_like_command(raw)
