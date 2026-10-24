"""Profile, security and workspace settings."""

import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import auth
import team
import totp
from auth import accessible_projects, admin_required, login_required
from db import dump_sql, execute, is_postgres, new_id, now_iso, query
from whatsapp import display_phone, normalize_phone

bp = Blueprint("settings", __name__)

DENSITIES = {"comfortable", "compact"}
PAGE_SIZES = {25, 50, 100}


@bp.get("/app/settings")
@login_required
def index():
    projects = accessible_projects(g.user)
    contacts = query(
        "SELECT * FROM whatsapp_contacts WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)
    )
    counts = {
        "projects": len(projects),
        "managed": len([project for project in projects if project["manager_id"] == g.user["id"]]),
        "expenses": query(
            "SELECT COUNT(*) AS count FROM transactions WHERE created_by = ?", (g.user["id"],), one=True
        )["count"],
    }

    is_manager = g.user["role"] == "manager"
    return render_template(
        "app/settings.html",
        title="Settings",
        active="settings",
        projects=projects,
        contacts=contacts,
        counts=counts,
        display_phone=display_phone,
        team_managers=[] if is_manager else team.managers_for(g.user["id"]),
        team_clients=team.clients_for(g.user["id"]) if is_manager else [],
        team_invites=[] if is_manager else team.pending_for_client(g.user["id"]),
        invite_url=team.invite_url,
    )


@bp.post("/app/settings/profile")
@login_required
def update_profile():
    name = (request.form.get("name") or "").strip()
    phone = normalize_phone(request.form.get("phone") or "")
    country = (request.form.get("country") or "").strip()
    colour = (request.form.get("avatar_color") or "").strip()

    if len(name) < 2:
        flash("Enter your full name.", "error")
        return redirect(url_for("settings.index"))

    if colour and not re.match(r"^#[0-9A-Fa-f]{6}$", colour):
        colour = g.user["avatar_color"]

    execute(
        "UPDATE users SET name = ?, phone = ?, country = ?, avatar_color = ? WHERE id = ?",
        (name[:90], phone or None, country[:80] or None, colour, g.user["id"]),
    )

    if phone:
        execute("UPDATE whatsapp_contacts SET user_id = ? WHERE phone = ?", (g.user["id"], phone))

    flash("Profile updated.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/app/settings/preferences")
@login_required
def update_preferences():
    """Row density and page size. Both are presentation only, so junk input
    falls back to what the user already had rather than erroring."""
    density = (request.form.get("density") or "").strip()
    if density not in DENSITIES:
        density = g.user["density"]

    try:
        page_size = int(request.form.get("page_size") or "")
    except (TypeError, ValueError):
        page_size = g.user["page_size"]
    if page_size not in PAGE_SIZES:
        page_size = g.user["page_size"]

    execute(
        "UPDATE users SET density = ?, page_size = ? WHERE id = ?",
        (density, page_size, g.user["id"]),
    )

    # The palette's density action posts here and stays on the current page.
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "density": density, "page_size": page_size})

    if request.form.get("save") == "1":
        flash("Display preferences saved.", "success")
    return redirect(url_for("settings.index"))


@bp.get("/app/settings/backup")
@admin_required
def backup():
    """A consistent copy of the database, with the uploads folder optional.

    Staff only: one client must never be able to download another client's
    receipts. The archive is streamed from a temp file, so a large uploads
    folder does not sit in memory.
    """
    include_uploads = request.args.get("uploads") != "0"
    uploads = Path(current_app.config["UPLOAD_FOLDER"])

    # send_file keeps the archive open while it streams, so cleanup cannot
    # happen on response teardown (Windows refuses to delete an open handle).
    # Sweep the working folders left behind by earlier runs instead.
    for stale in Path(tempfile.gettempdir()).glob("vaka-backup-*"):
        try:
            if time.time() - stale.stat().st_mtime <= 3600:
                continue
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            else:
                stale.unlink()
        except OSError:
            pass

    workdir = Path(tempfile.mkdtemp(prefix="vaka-backup-"))
    archive_path = workdir / "backup.zip"
    snapshot_name = "vaka.sql" if is_postgres() else "vaka.db"
    snapshot_path = workdir / snapshot_name

    if is_postgres():
        snapshot_path.write_text(dump_sql(), encoding="utf-8")
    else:
        database = Path(current_app.config["DATABASE"])
        source = sqlite3.connect(str(database))
        target = sqlite3.connect(str(snapshot_path))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot_path, snapshot_name)
        if include_uploads and uploads.is_dir():
            for path in sorted(uploads.rglob("*")):
                if path.is_file():
                    archive.write(path, f"uploads/{path.relative_to(uploads).as_posix()}")

    stamp = datetime.now().strftime("%Y-%m-%d")
    return send_file(
        archive_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"yavaka-backup-{stamp}.zip",
    )


@bp.post("/app/settings/password")
@login_required
def update_password():
    current = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    user = query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)

    if not auth.verify_password(current, user["password_hash"]):
        flash("Your current password is not correct.", "error")
    elif len(new_password) < 8:
        flash("The new password must be at least 8 characters.", "error")
    elif new_password != confirm:
        flash("The new passwords do not match.", "error")
    else:
        execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (auth.hash_password(new_password), g.user["id"]),
        )
        # Every other device signed in with the old password is retired; this
        # browser is re-seated on the new epoch by the helper.
        auth.bump_session_epoch(g.user["id"])
        auth.audit_auth("password.changed", user_id=g.user["id"])
        flash("Password changed. Other devices have been signed out.", "success")

    return redirect(url_for("settings.index"))


@bp.post("/app/settings/sessions")
@login_required
def revoke_sessions():
    auth.bump_session_epoch(g.user["id"])
    auth.audit_auth("session.revoked_all", user_id=g.user["id"])
    flash("Every other device has been signed out.", "success")
    return redirect(url_for("settings.index"))


@bp.get("/app/settings/2fa")
@login_required
def two_factor_setup():
    if int(g.user["totp_enabled"] or 0):
        return redirect(url_for("settings.index"))

    secret = session.get("totp_setup_secret")
    if not secret:
        secret = totp.generate_secret()
        session["totp_setup_secret"] = secret

    return render_template(
        "app/two_factor_setup.html",
        title="Two-step verification",
        active="settings",
        projects=accessible_projects(g.user),
        secret=secret,
        grouped=" ".join(secret[i : i + 4] for i in range(0, len(secret), 4)),
        provisioning_uri=totp.provisioning_uri(secret, g.user["email"]),
    )


@bp.post("/app/settings/2fa")
@login_required
def two_factor_enable():
    secret = session.get("totp_setup_secret") or ""
    code = (request.form.get("code") or "").strip()
    password = request.form.get("password") or ""

    user = query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)

    if not auth.verify_password(password, user["password_hash"]):
        flash("Your password is not correct.", "error")
        return redirect(url_for("settings.two_factor_setup"))
    if not secret or not totp.verify(secret, code):
        flash("That code is not correct. Check the time on your phone and try again.", "error")
        return redirect(url_for("settings.two_factor_setup"))

    codes = totp.generate_recovery_codes()
    execute(
        "UPDATE users SET totp_secret = ?, totp_enabled = 1 WHERE id = ?",
        (secret, g.user["id"]),
    )
    execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (g.user["id"],))
    for code_value in codes:
        execute(
            """INSERT INTO totp_recovery_codes (id, user_id, code_hash, created_at)
               VALUES (?, ?, ?, ?)""",
            (new_id(), g.user["id"], totp.hash_code(code_value), now_iso()),
        )
    session.pop("totp_setup_secret", None)
    auth.audit_auth("2fa.enabled", user_id=g.user["id"])

    return render_template(
        "app/two_factor_codes.html",
        title="Recovery codes",
        active="settings",
        projects=accessible_projects(g.user),
        codes=codes,
    )


@bp.post("/app/settings/2fa/disable")
@login_required
def two_factor_disable():
    password = request.form.get("password") or ""
    user = query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)

    if not auth.verify_password(password, user["password_hash"]):
        flash("Your password is not correct.", "error")
    else:
        execute(
            "UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?",
            (g.user["id"],),
        )
        execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (g.user["id"],))
        auth.audit_auth("2fa.disabled", user_id=g.user["id"])
        flash("Two-step verification is off.", "success")

    return redirect(url_for("settings.index"))
