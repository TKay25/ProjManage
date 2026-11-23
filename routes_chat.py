"""The conversation as the front door of each workspace."""

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

import chat
import portals
import rentals
import services
import web
from auth import login_required, portal_required

bp = Blueprint("chat", __name__)

STARTERS = {
    portals.PROJECT: (
        "What needs attention?",
        "How much have I spent on cement?",
        "Spent 340 on cement",
        "Post an update that the slab is done",
    ),
    portals.PROPERTY: (
        "How much rent is outstanding?",
        "Receipt 450 rent",
        "Fix the geyser, it is urgent",
        "Add a tenant",
    ),
}


def _home_endpoint(portal: str) -> str:
    return "chat.property_home" if portal == portals.PROPERTY else "chat.home"


def _page(portal: str):
    thread = chat.thread_for(g.user, portal)
    chat.ensure_greeting(g.user, thread)
    projects = chat.projects_for(g.user) if portal == portals.PROJECT else []
    project = chat.current_project(g.user, thread) if portal == portals.PROJECT else None
    # Pin the build the greeting names, so a later sentence cannot land on a
    # different one just because another build was touched in between.
    if project:
        chat.remember_project(thread, project["id"])
    context = {
        "title": "Home",
        "active": "home",
        "portal": portal,
        "thread": thread,
        "events": chat.history(thread["id"]),
        "projects": projects,
        "project": project,
        "starter_prompts": list(STARTERS.get(portal, STARTERS[portals.PROJECT])),
        "home_endpoint": _home_endpoint(portal),
    }
    if portal == portals.PROPERTY:
        context["property_count"] = len(rentals.portfolio(g.user["id"]))
    return render_template("chat/index.html", **context)


@bp.get("/app")
@login_required
def home():
    return _page(portals.PROJECT)


@bp.get("/property")
@portal_required(portals.PROPERTY)
def property_home():
    return _page(portals.PROPERTY)


def _send(portal: str):
    thread = chat.thread_for(g.user, portal)
    text = (request.form.get("text") or "").strip()
    if not text:
        return redirect(url_for(_home_endpoint(portal)))

    # A tapped button sends the label it showed, so the transcript reads like a
    # conversation rather than a stream of internal values.
    events = chat.turn(g.user, thread, text, request.form.get("label"))
    if web.wants_json():
        return jsonify(
            {"ok": True, "html": render_template("chat/_events.html", events=events)}
        )
    return redirect(url_for(_home_endpoint(portal)))


@bp.post("/app/chat")
@login_required
def send_project():
    return _send(portals.PROJECT)


@bp.post("/property/chat")
@portal_required(portals.PROPERTY)
def send_property():
    return _send(portals.PROPERTY)


@bp.post("/app/chat/project")
@login_required
def switch_project():
    project_id = (request.form.get("project") or "").strip()
    thread = chat.thread_for(g.user, portals.PROJECT)
    try:
        reply = chat.switch_project(g.user, thread, project_id)
    except services.ServiceError as error:
        if web.wants_json():
            return web.fail(str(error))
        return redirect(url_for("chat.home"))

    event = chat.post(
        thread["id"],
        "assistant",
        reply["body"],
        card=reply.get("card"),
        actions=reply.get("actions"),
    )
    if web.wants_json():
        return jsonify(
            {"ok": True, "html": render_template("chat/_events.html", events=[event])}
        )
    return redirect(url_for("chat.home"))
