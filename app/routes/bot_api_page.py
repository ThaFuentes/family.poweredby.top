"""The key guide as a page. Same text the key reads from GET /api/v1/helper.

A bot opens its own. A leader opens it from People for that bot. It does
not show secrets, and it does not let the account do more than its role.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from app.utils.bot_api_help import call_allowed, help_for
from app.utils.bot_api_keys import SCOPE_ALL, SCOPE_VAULT, normalize_scope, scope_label
from app.utils.permissions import can, role_of

bot_guide_bp = Blueprint("bot_guide", __name__)


def _same_house(bot) -> bool:
    return int(getattr(bot, "household_id", 0) or 0) == int(getattr(current_user, "household_id", 0) or 0)


def _may_read(bot) -> bool:
    if bot is None or not _same_house(bot):
        return False
    if int(getattr(bot, "id", 0) or 0) == int(getattr(current_user, "id", 0) or 0):
        return bool(getattr(current_user, "is_bot", False))
    return can("members") or bool(getattr(current_user, "is_leader", False))


def _page(bot):
    if not bool(getattr(bot, "is_bot", False)) or not _may_read(bot):
        abort(404)
    scope = normalize_scope(request.args.get("scope") or SCOPE_ALL)
    if scope not in (SCOPE_ALL, SCOPE_VAULT):
        scope = SCOPE_ALL
    pack = help_for(scope)
    rows = []
    for call in pack["calls"]:
        rows.append({**call, "open": call_allowed(bot, call.get("needs") or "")})
    if int(getattr(bot, "id", 0) or 0) == int(getattr(current_user, "id", 0) or 0):
        house_href = "/bot-api/guide?scope=fos_bot_"
        vault_href = "/bot-api/guide?scope=fos_vault_"
    else:
        house_href = f"/members/{bot.id}/bot-api/guide?scope=fos_bot_"
        vault_href = f"/members/{bot.id}/bot-api/guide?scope=fos_vault_"
    return render_template(
        "bot_api_guide.html",
        bot=bot,
        scope=scope,
        scope_label=scope_label(scope),
        guide=pack["guide"],
        rows=rows,
        examples=pack["examples"],
        role=role_of(bot),
        house_href=house_href,
        vault_href=vault_href,
    )


@bot_guide_bp.route("/bot-api/guide")
@login_required
def own():
    return _page(current_user)


@bot_guide_bp.route("/members/<int:user_id>/bot-api/guide")
@login_required
def for_member(user_id):
    from app.builddb.table_users import User

    bot = User.query.filter_by(id=user_id, household_id=getattr(current_user, "household_id", None)).first()
    return _page(bot)
