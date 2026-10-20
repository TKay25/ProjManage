"""Request/response helpers shared by the blueprints.

Every mutating route supports two response styles:

* a normal HTML form post  -> flash + redirect (works without JavaScript)
* an enhanced modal submit  -> JSON with an optional HTML fragment to patch in

That keeps the app usable if JavaScript fails while letting the UI behave like a
single-page app when it does not.
"""

from flask import jsonify, redirect, request, url_for

# Regions of a page an AJAX response is allowed to replace.
PATCH_MODES = {"replace", "prepend", "append", "innerHTML", "remove"}


def wants_json() -> bool:
    """True when the request came from the fetch-based form enhancer."""
    if request.headers.get("X-Requested-With") == "fetch":
        return True
    return (
        request.accept_mimetypes.best == "application/json"
        and request.accept_mimetypes["application/json"]
        > request.accept_mimetypes["text/html"]
    )


def ok(
    message,
    *,
    fragment=None,
    target=None,
    mode="replace",
    fields=None,
    html=None,
    redirect_to=None,
    reload=False,
    status=200,
    title=None,
):
    """Successful JSON response, optionally patching part of the current page.

    A fragment without a target is content for a reader dialog: the client drops
    it into the shared modal body instead of replacing part of the page. ``fields``
    sets plain text; ``html`` swaps inner markup (badges, chips) where the styling
    has to change too.
    """
    payload = {"ok": True, "message": message}
    if fragment:
        payload["fragment"] = str(fragment)
        if target:
            payload["target"] = target
            payload["mode"] = mode if mode in PATCH_MODES else "replace"
    if fields:
        payload["fields"] = fields
    if html:
        payload["html"] = html
    if redirect_to:
        payload["redirect"] = redirect_to
    if reload:
        payload["reload"] = True
    if title:
        payload["title"] = title
    return jsonify(payload), status


def fail(message, *, status=400, fields=None):
    """Validation failure that the modal should show without closing."""
    payload = {"ok": False, "message": message}
    if fields:
        payload["fields"] = fields
    return jsonify(payload), status


def bounce(endpoint, *, message=None, category="error", **values):
    """Fallback path: flash and redirect back to a page when JavaScript is off."""
    from flask import flash

    if message:
        flash(message, category)
    return redirect(url_for(endpoint, **values))
