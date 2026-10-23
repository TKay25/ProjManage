"""Inviting a build manager, accepting the link, and managing the team."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import login_required
from db import log_event, query
from web import fail, ok, wants_json
import team

bp = Blueprint("team", __name__)

@bp.get("/invite/<token>")
def invite_landing(token):
    invitation = team.invitation_by_token(token)
    if not invitation:
        abort(404)

    signed_in = g.user is not None
    matches = signed_in and (g.user["email"] or "").lower() == invitation["email"]
    return render_template(
        "invite.html",
        title="Build manager invitation",
        invitation=invitation,
        signed_in=signed_in,
        matches=matches,
        token=token,
    )


@bp.post("/invite/<token>")
def invite_accept(token):
    if not g.user:
        return redirect(url_for("auth.login", next=url_for("team.invite_landing", token=token)))

    result = team.accept(token, g.user)
    if not result["ok"]:
        flash(result["message"], "error")
        return redirect(url_for("team.invite_landing", token=token))

    invitation = result["invitation"]
    log_event(g.user["id"], invitation["project_id"], "team.joined", result["message"])
    flash(result["message"], "success")
    return redirect(url_for("projects.index"))


@bp.post("/app/team/invite")
@login_required
def invite():
    """Invite a build manager to the client's builds, from Settings or a project."""
    project_id = request.form.get("project_id") or None
    email = (request.form.get("email") or "").strip().lower()

    project = None
    if project_id:
        project = query("SELECT * FROM projects WHERE id = ?", (project_id,), one=True)
        if not project or project["owner_id"] != g.user["id"]:
            abort(404)

    result = team.invite(g.user, email, project_id=project_id if project else None)

    if not result["ok"]:
        if wants_json():
            return fail(result["message"])
        flash(result["message"], "error")
        return redirect(url_for("settings.index") if not project else url_for("projects.detail", project_id=project_id))

    if result["invitation"]:
        team.email_invitation(result["invitation"], g.user, project)
        log_event(
            g.user["id"],
            project["id"] if project else None,
            "team.invited",
            f"Invitation sent to {email}",
        )
    elif result["linked"]:
        log_event(
            g.user["id"],
            project["id"] if project else None,
            "team.linked",
            f"{result['linked']['name']} added as build manager",
        )

    if wants_json():
        return ok(result["message"], reload=True)

    flash(result["message"], "success")
    if project:
        return redirect(url_for("projects.detail", project_id=project_id) + "#team")
    return redirect(url_for("settings.index") + "#team")


@bp.post("/app/team/<invitation_id>/revoke")
@login_required
def revoke(invitation_id):
    if not team.revoke(invitation_id, g.user["id"]):
        flash("That invitation is no longer pending.", "error")
    else:
        flash("Invitation withdrawn.", "success")
    return redirect(url_for("settings.index") + "#team")


@bp.post("/app/team/<manager_id>/remove")
@login_required
def remove(manager_id):
    """Stop a manager seeing this client's builds. Per-project assignment clears too."""
    if team.unlink(g.user["id"], manager_id):
        # The team link is what granted access; also clear the explicit
        # per-project assignment so nothing is left pointing at them.
        from db import execute, now_iso

        execute(
            "UPDATE projects SET manager_id = NULL, updated_at = ? WHERE owner_id = ? AND manager_id = ?",
            (now_iso(), g.user["id"], manager_id),
        )
        log_event(g.user["id"], None, "team.removed", "Build manager removed from the team")
        flash("Build manager removed from your builds.", "success")
    else:
        flash("That person is not on your team.", "error")
    return redirect(url_for("settings.index") + "#team")
