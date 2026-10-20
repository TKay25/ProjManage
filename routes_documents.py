"""Document vault: receipts, statutory approvals, photos and handover files."""

from pathlib import Path

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for

from auth import accessible_projects, can_manage_project, login_required, require_project
from db import execute, log_event, new_id, now_iso, query
from storage import UploadError, delete_upload, save_upload
import web

bp = Blueprint("documents", __name__)

KINDS = {
    "receipt": "Receipt",
    "document": "Document",
    "photo": "Site photo",
}


@bp.get("/app/documents")
@login_required
def index():
    projects = accessible_projects(g.user)
    requested = request.args.get("project")
    project = next((item for item in projects if item["id"] == requested), None)

    params = []
    where = []
    if project:
        where.append("a.project_id = ?")
        params.append(project["id"])
    elif projects:
        placeholders = ",".join("?" for _ in projects)
        where.append(f"a.project_id IN ({placeholders})")
        params.extend([item["id"] for item in projects])

    kind = request.args.get("kind", "")
    if kind in KINDS:
        where.append("a.kind = ?")
        params.append(kind)

    attachments = []
    if where:
        attachments = query(
            f"""SELECT a.*, u.name AS uploader_name, p.name AS project_name, t.description AS transaction_description
                FROM attachments a
                LEFT JOIN users u ON u.id = a.uploader_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN transactions t ON t.id = a.transaction_id
                WHERE {' AND '.join(where)}
                ORDER BY a.created_at DESC
                LIMIT 200""",
            params,
        )

    total_size = sum(item["size"] or 0 for item in attachments)

    return render_template(
        "app/documents.html",
        title="Documents",
        active="documents",
        projects=projects,
        project=project,
        attachments=attachments,
        kinds=KINDS,
        kind=kind,
        total_size=total_size,
    )


@bp.post("/app/documents/upload")
@login_required
def upload():
    project = require_project(request.form.get("project_id") or "")
    kind = request.form.get("kind") or "document"
    if kind not in KINDS:
        kind = "document"

    try:
        saved = save_upload(request.files.get("file"), kind)
    except UploadError as error:
        if web.wants_json():
            return web.fail(str(error))
        flash(str(error), "error")
        return redirect(url_for("documents.index", project=project["id"]))

    attachment_id = new_id()
    execute(
        """INSERT INTO attachments
             (id, project_id, transaction_id, uploader_id, kind, filename, original_name, mime_type, size, created_at)
           VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (
            attachment_id,
            project["id"],
            g.user["id"],
            kind,
            saved["filename"],
            saved["original_name"],
            saved["mime_type"],
            saved["size"],
            now_iso(),
        ),
    )

    log_event(g.user["id"], project["id"], "document.uploaded", saved["original_name"])

    if web.wants_json():
        file_row = query(
            """SELECT a.*, u.name AS uploader_name, p.name AS project_name, NULL AS transaction_description
               FROM attachments a
               LEFT JOIN users u ON u.id = a.uploader_id
               LEFT JOIN projects p ON p.id = a.project_id
               WHERE a.id = ?""",
            (attachment_id,),
            one=True,
        )
        return web.ok(
            f"{KINDS[kind]} uploaded.",
            fragment=render_template("partials/doc_card.html", file=file_row, kinds=KINDS),
            target="[data-doc-grid]",
            mode="prepend",
        )

    flash(f"{KINDS[kind]} uploaded.", "success")
    return redirect(url_for("documents.index", project=project["id"]))


@bp.get("/files/<attachment_id>")
@login_required
def serve(attachment_id):
    attachment = query("SELECT * FROM attachments WHERE id = ?", (attachment_id,), one=True)

    if not attachment:
        abort(404)

    project = query("SELECT * FROM projects WHERE id = ?", (attachment["project_id"],), one=True)
    if not can_manage_project(g.user, project):
        abort(404)

    directory = Path(current_app.config["UPLOAD_FOLDER"])
    download = request.args.get("download") == "1"

    return send_from_directory(
        directory,
        attachment["filename"],
        mimetype=attachment["mime_type"],
        as_attachment=download,
        download_name=attachment["original_name"] if download else None,
    )


@bp.post("/app/documents/<attachment_id>/delete")
@login_required
def delete(attachment_id):
    attachment = query("SELECT * FROM attachments WHERE id = ?", (attachment_id,), one=True)

    if not attachment:
        flash("That document no longer exists.", "error")
        return redirect(url_for("documents.index"))

    project = require_project(attachment["project_id"])
    delete_upload(attachment["filename"])
    execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    log_event(g.user["id"], project["id"], "document.deleted", attachment["original_name"])

    if web.wants_json():
        return web.ok("Document removed.", fragment="", target=f"#doc-{attachment_id}", mode="remove")

    flash("Document removed.", "success")
    return redirect(url_for("documents.index", project=project["id"]))
