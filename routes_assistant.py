"""The assistant endpoint behind the floating window."""

from flask import Blueprint, jsonify, request

from auth import login_required
from flask import g
import assistant

bp = Blueprint("assistant", __name__)

MAX_QUESTION = 300


@bp.post("/api/assistant/ask")
@login_required
def ask():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()[:MAX_QUESTION]
    if not question:
        return jsonify({"ok": False, "error": "Ask me something first."}), 400

    result = assistant.answer(g.user, question)
    return jsonify({"ok": True, **result})


@bp.get("/api/assistant/suggestions")
@login_required
def suggestions():
    return jsonify({"ok": True, "suggestions": list(assistant.suggestions_for(g.user))})
