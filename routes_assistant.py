"""The assistant endpoint behind the floating window."""

from flask import Blueprint, g, jsonify, request

import assistant

bp = Blueprint("assistant", __name__)

MAX_QUESTION = 300


@bp.post("/api/assistant/ask")
def ask():
    """Signed-in people get their own figures; visitors get product answers.

    Deliberately not @login_required: the landing page carries the same
    assistant, and a stranger asking what YaVaKa is should get an answer rather
    than a redirect to a sign-in form.
    """
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()[:MAX_QUESTION]
    if not question:
        return jsonify({"ok": False, "error": "Ask me something first."}), 400

    if g.user:
        result = assistant.answer(g.user, question)
    else:
        result = assistant.answer_public(question)
    return jsonify({"ok": True, **result})


@bp.get("/api/assistant/suggestions")
def suggestions():
    return jsonify({"ok": True, "suggestions": list(assistant.suggestions_for(g.user))})
