"""Shared household actions.

The web pages (``app/routes/*``) and Maya's API (``app/routes/maya_api.py``)
both call these functions, so a change made through the API is the exact same
database work as the button in the app, with the same Happened rows. Callers
handle their own HTTP (flash/redirect for pages, JSON for the API) and their
own permission checks; these functions do the work and the bookkeeping.

``current_user`` is the actor in both cases: Maya's API binds her bot account
as ``current_user`` for the request, so ``scoped()`` and the activity log see
her the same way they see a signed-in person.
"""
