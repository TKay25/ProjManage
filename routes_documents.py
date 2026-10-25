"""Document vault: receipts, statutory approvals, photos and handover files."""

from pathlib import Path

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for

from auth import accessible_projects, can_manage_project, login_required, require_project
from db import execute, log_event, new_id, now_iso, query
from notifications import queue_manager_update
from paging import offset, page_number, page_size, page_window
from stages import STAGE_GROUPS, stage_by_key
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

    stage_key = request.args.get("stage", "")
    if stage_key:
        where.append("a.stage_key = ?")
        params.append(stage_key)

    attachments = []
    total_rows = 0
    total_size = 0
    page, page_count = 1, 1
    if where:
        clause = " AND ".join(where)
        totals = query(
            f"""SELECT COUNT(*) AS total, COALESCE(SUM(a.size), 0) AS bytes
                FROM attachments a WHERE {clause}""",
            params,
            one=True,
        )
        total_rows = int(totals["total"] or 0)
        total_size = int(totals["bytes"] or 0)

        size = page_size()
        page, page_count = page_window(page_number(), total_rows, size)

        attachments = query(
            f"""SELECT a.*, u.name AS uploader_name, p.name AS project_name,
                       t.description AS transaction_description, s.name AS stage_name
                FROM attachments a
                LEFT JOIN users u ON u.id = a.uploader_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN transactions t ON t.id = a.transaction_id
                LEFT JOIN stages s ON s.project_id = a.project_id AND s.key = a.stage_key
                WHERE {clause}
                ORDER BY a.created_at DESC
                LIMIT ? OFFSET ?""",
            [*params, size, offset(page, size)],
        )

    stage_groups = []
    if project:
        rows = {row["key"]: row for row in query(
            "SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project["id"],)
        )}
        for group in STAGE_GROUPS:
            items = [row for key, row in rows.items() if stage_by_key(key) and stage_by_key(key)["group"] == group]
            stage_groups.append({"name": group, "stages": items})

    return render_template(
        "app/documents.html",
        title="Documents",
        active="documents",
        projects=projects,
        project=project,
        attachments=attachments,
        kinds=KINDS,
        kind=kind,
        stage_key=stage_key,
        stage_groups=stage_groups,
        total_size=total_size,
        total_rows=total_rows,
        page=page,
        page_count=page_count,
        pager_endpoint="documents.index",
        pager_args={"project": project["id"] if project else "", "kind": kind, "stage": stage_key},
    )


@bp.post("/app/documents/upload")
@login_required
def upload():
    project = require_project(request.form.get("project_id") or "")
    kind = request.form.get("kind") or "document"
    if kind not in KINDS:
        kind = "document"

    # Only accept a stage that actually belongs to this project.
    stage_key = request.form.get("stage_key") or None
    if stage_key and not query(
        "SELECT 1 FROM stages WHERE project_id = ? AND key = ?", (project["id"], stage_key), one=True
    ):
        stage_key = None

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
             (id, project_id, transaction_id, uploader_id, kind, filename, original_name, mime_type, size, stage_key, created_at)
           VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            attachment_id,
            project["id"],
            g.user["id"],
            kind,
            saved["filename"],
            saved["original_name"],
            saved["mime_type"],
            saved["size"],
            stage_key,
            now_iso(),
        ),
    )

    log_event(g.user["id"], project["id"], "document.uploaded", saved["original_name"])

    # The notification carries a link, because a WhatsApp template cannot carry
    # a file and the recipient may not have a login.
    import downloads

    queue_manager_update(
        project["id"],
        g.user["id"],
        g.user["name"],
        "Project file uploaded",
        saved["original_name"],
        link=downloads.absolute_url(attachment_id),
        file_name=saved["original_name"],
    )

    if web.wants_json():
        file_row = query(
            """SELECT a.*, u.name AS uploader_name, p.name AS project_name,
                      NULL AS transaction_description, s.name AS stage_name
               FROM attachments a
               LEFT JOIN users u ON u.id = a.uploader_id
               LEFT JOIN projects p ON p.id = a.project_id
               LEFT JOIN stages s ON s.project_id = a.project_id AND s.key = a.stage_key
               WHERE a.id = ?""",
            (attachment_id,),
            one=True,
        )
        message = f"{KINDS[kind]} uploaded."

        # Filed from a stage: drop it straight into that stage's file list.
        if stage_key:
            return web.ok(
                message,
                fragment=render_template("partials/stage_file_row.html", file=file_row),
                target=f'[data-stage-files="{stage_key}"]',
                mode="prepend",
            )

        return web.ok(
            message,
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


@bp.get("/d/<token>")
def download(token):
    """Tokenised download for links sent over WhatsApp.

    Deliberately not @login_required: a client may have no YaVaKa account. The
    HMAC in the token is what authorises the read, and it expires.
    """
    import downloads

    attachment_id = downloads.verify(token)
    if not attachment_id:
        abort(404)

    attachment = query(
        "SELECT * FROM attachments WHERE id = ?", (attachment_id,), one=True
    )
    if not attachment:
        abort(404)

    directory = Path(current_app.config["UPLOAD_FOLDER"])
    return send_from_directory(
        directory,
        attachment["filename"],
        mimetype=attachment["mime_type"],
        as_attachment=True,
        download_name=attachment["original_name"],
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
