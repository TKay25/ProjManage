"""Registration, login, logout and password reset."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import auth
import team
import totp
import web
from db import execute, new_id, now_iso, query
from whatsapp import normalize_phone

bp = Blueprint("auth", __name__)

# Avatar initials are white on these, so every one must clear 4.5:1. Brass was
# #C8963E (2.7:1); #8F6524 keeps the same hue at 5.2:1.
AVATAR_COLORS = ["#0F5D46", "#8F6524", "#2A7A5E", "#A9573C", "#3E6B8A", "#6B5B95"]
MAX_ATTEMPTS = 8
RESET_TTL = timedelta(hours=1)
# How long a correct password may wait for its second factor.
PENDING_2FA_KEY = "pending_2fa"
PENDING_TTL = timedelta(minutes=5)


def _reset_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_reset(token: str):
    """A reset row that is still usable, or None."""
    if not token:
        return None
    row = query(
        """SELECT r.*, u.email, u.name
           FROM password_resets r
           JOIN users u ON u.id = r.user_id
           WHERE r.token_hash = ?""",
        (_reset_hash(token),),
        one=True,
    )
    if not row or row["used_at"]:
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        return None
    if expires <= datetime.now(timezone.utc):
        return None
    return row


def _is_blocked(key: str) -> bool:
    """Only failed attempts are recorded, so a legitimate sign-in never counts."""
    return auth.throttle_blocked(key, MAX_ATTEMPTS)


def _register_failure(key: str):
    auth.throttle_failure(key)


def _clear_attempts(key: str):
    auth.throttle_clear(key)


def _client_key(scope: str, email: str) -> str:
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "")).split(",")[0].strip()
    return f"{scope}:{ip}:{email}"


def _pending_two_factor():
    """The verified-password state waiting for a TOTP code, or None."""
    pending = session.get(PENDING_2FA_KEY)
    if not pending:
        return None
    try:
        started = datetime.fromisoformat(pending["started"])
    except (KeyError, TypeError, ValueError):
        session.pop(PENDING_2FA_KEY, None)
        return None
    if datetime.now(timezone.utc) - started > PENDING_TTL:
        session.pop(PENDING_2FA_KEY, None)
        return None
    return pending


def _finish_login(user, next_url: str):
    session.pop(PENDING_2FA_KEY, None)
    auth.login_user(user["id"])
    auth.audit_auth("login.success", user["email"], user_id=user["id"])
    message = f"Welcome back, {user['name'].split()[0]}."

    if web.wants_json():
        # The dialog hands off to a page load, so flash rather than toast.
        flash(message, "success")
        return web.ok(message, redirect_to=next_url or url_for("dashboard.index"))

    flash(message, "success")
    return redirect(next_url)


def _colour_for(email: str) -> str:
    return AVATAR_COLORS[sum(ord(char) for char in email) % len(AVATAR_COLORS)]


@bp.get("/login")
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    return render_template(
        "auth/login.html",
        title="Welcome back",
        email="",
        error=None,
        next=auth.safe_next(request.args.get("next", "")),
    )


@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    next_url = auth.safe_next(request.form.get("next", ""))
    throttle_key = _client_key("login", email)

    def failure(message, status):
        if web.wants_json():
            return web.fail(message, status=status)
        return (
            render_template(
                "auth/login.html",
                title="Welcome back",
                email=email,
                error=message,
                next=next_url,
            ),
            status,
        )

    if _is_blocked(throttle_key):
        return failure("Too many attempts. Wait 15 minutes and try again.", 429)

    user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

    if not user or not auth.verify_password(password, user["password_hash"]):
        _register_failure(throttle_key)
        auth.audit_auth(
            "login.failed",
            f"{email} from {request.remote_addr}",
            user_id=user["id"] if user else None,
        )
        return failure("That email and password do not match.", 401)

    _clear_attempts(throttle_key)

    if int(user["totp_enabled"] or 0):
        session[PENDING_2FA_KEY] = {
            "user_id": user["id"],
            "next": next_url,
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return redirect(url_for("auth.two_factor"))

    return _finish_login(user, next_url)


@bp.route("/login/2fa", methods=["GET", "POST"])
def two_factor():
    """Second step for accounts with an authenticator app enrolled."""
    pending = _pending_two_factor()
    if not pending:
        flash("Sign in again to continue.", "error")
        return redirect(url_for("auth.login"))
    if g.user:
        return redirect(url_for("dashboard.index"))

    user = query(
        "SELECT * FROM users WHERE id = ?",
        (pending["user_id"],),
        one=True,
    )
    if not user or not int(user["totp_enabled"] or 0):
        session.pop(PENDING_2FA_KEY, None)
        return redirect(url_for("auth.login"))

    throttle_key = _client_key("2fa", user["email"])
    error = None

    if request.method == "POST":
        supplied = (request.form.get("code") or "").strip()
        if _is_blocked(throttle_key):
            error = "Too many attempts. Wait 15 minutes and try again."
        elif _consume_recovery_code(user["id"], supplied) or totp.verify(
            user["totp_secret"] or "", supplied
        ):
            _clear_attempts(throttle_key)
            return _finish_login(user, pending.get("next") or "")
        else:
            _register_failure(throttle_key)
            auth.audit_auth("login.2fa_failed", user["email"], user_id=user["id"])
            error = "That code is not correct. Try the next one."

    return (
        render_template(
            "auth/two_factor.html",
            title="Two-step verification",
            error=error,
            remaining=_recovery_remaining(user["id"]),
        ),
        429 if error and error.startswith("Too many") else 200,
    )


def _consume_recovery_code(user_id: str, supplied: str) -> bool:
    """Uses one recovery code up. They are single-use by design."""
    candidate = (supplied or "").strip()
    if len(candidate.replace("-", "")) < 8:
        return False

    hashed = totp.hash_code(candidate)
    row = query(
        """SELECT id FROM totp_recovery_codes
           WHERE user_id = ? AND code_hash = ? AND used_at IS NULL""",
        (user_id, hashed),
        one=True,
    )
    if not row:
        return False

    execute("UPDATE totp_recovery_codes SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
    auth.audit_auth("login.recovery_code", user_id=user_id)
    return True


def _recovery_remaining(user_id: str) -> int:
    row = query(
        """SELECT COUNT(*) AS total FROM totp_recovery_codes
           WHERE user_id = ? AND used_at IS NULL""",
        (user_id,),
        one=True,
    )
    return int(row["total"] or 0)


@bp.get("/forgot-password")
def forgot_password():
    if g.user:
        return redirect(url_for("dashboard.index"))
    return render_template(
        "auth/forgot_password.html",
        title="Reset your password",
        email="",
    )


@bp.post("/forgot-password")
def forgot_password_post():
    email = (request.form.get("email") or "").strip().lower()
    throttle_key = _client_key("reset", email)

    if _is_blocked(throttle_key):
        flash("Too many attempts. Wait 15 minutes and try again.", "error")
        return redirect(url_for("auth.forgot_password"))

    from notifications import email_configured, send_email_async

    if not email_configured():
        flash(
            "Email delivery is not configured on this deployment, so the reset "
            "link cannot be sent. Ask your build manager to reset the password.",
            "error",
        )
        return redirect(url_for("auth.forgot_password"))

    # Count every request, valid address or not, so the endpoint cannot be used
    # to mail-bomb an inbox.
    _register_failure(throttle_key)
    user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

    if user:
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + RESET_TTL).isoformat(timespec="microseconds")
        execute(
            "DELETE FROM password_resets WHERE user_id = ? AND used_at IS NULL",
            (user["id"],),
        )
        execute(
            """INSERT INTO password_resets (id, user_id, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (new_id(), user["id"], _reset_hash(token), expires, now_iso()),
        )
        link = url_for("auth.reset_password", token=token, _external=True)
        send_email_async(
            user["email"],
            "Reset your YaVaKa password",
            "\n".join(
                [
                    f"Hello {user['name']},",
                    "",
                    "Use this link to choose a new password. It expires in one hour:",
                    "",
                    link,
                    "",
                    "If you did not ask for this, you can ignore this email.",
                ]
            ),
        )

    flash(
        "If that address is registered, a reset link is on its way. "
        "Check your inbox and spam folder.",
        "success",
    )
    return redirect(url_for("auth.login"))


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if g.user:
        return redirect(url_for("dashboard.index"))

    row = _load_reset(token)
    if not row:
        return (
            render_template(
                "auth/reset_password.html",
                title="Reset password",
                token="",
                valid=False,
                error=None,
                email="",
            ),
            400,
        )

    error = None
    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        if len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "The passwords do not match."
        else:
            execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (auth.hash_password(password), row["user_id"]),
            )
            execute(
                "UPDATE password_resets SET used_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
            execute(
                "DELETE FROM password_resets WHERE user_id = ? AND id <> ?",
                (row["user_id"], row["id"]),
            )
            # Retire every session opened with the old password.
            execute(
                "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
                (row["user_id"],),
            )
            auth.audit_auth("password.reset", row["email"], user_id=row["user_id"])
            flash("Password changed. Sign in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "auth/reset_password.html",
        title="Choose a new password",
        token=token,
        valid=True,
        error=error,
        email=row["email"],
    )


@bp.get("/register")
def register():
    if g.user:
        return redirect(url_for("dashboard.index"))
    return render_template(
        "auth/register.html",
        title="Create your account",
        values={"email": request.args.get("email", "").strip().lower()},
        invite=request.args.get("invite", ""),
        error=None,
    )


@bp.post("/register")
def register_post():
    values = {
        "name": (request.form.get("name") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
        "phone": (request.form.get("phone") or "").strip(),
        "country": request.form.get("country") or "Zimbabwe",
        "role": request.form.get("role") or "client",
    }
    invite_token = (request.form.get("invite") or "").strip()
    password = request.form.get("password") or ""
    error = None

    if not values["name"] or len(values["name"]) > 90:
        error = "Enter your full name."
    elif "@" not in values["email"] or "." not in values["email"].split("@")[-1]:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif request.form.get("terms") != "yes":
        error = "Please confirm you understand what YaVaKa is."
    elif query("SELECT id FROM users WHERE email = ?", (values["email"],), one=True):
        error = "An account with that email already exists."

    if error:
        if web.wants_json():
            return web.fail(error)
        return (
            render_template(
                "auth/register.html",
                title="Create your account",
                values=values,
                invite=invite_token,
                error=error,
            ),
            400,
        )

    user_id = new_id()
    role = "manager" if values["role"] == "manager" else "client"

    execute(
        """INSERT INTO users (id, name, email, password_hash, role, phone, country, avatar_color, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            values["name"],
            values["email"],
            auth.hash_password(password),
            role,
            normalize_phone(values["phone"]) or None,
            values["country"][:80],
            _colour_for(values["email"]),
            now_iso(),
        ),
    )

    message = "Account created successfully. Sign in with your new credentials."

    # Two things can be waiting for a brand-new account: invitations addressed to
    # this address, and projects a manager filed for this client's email.
    new_user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    try:
        claimed = team.accept_pending_for(new_user)
        adopted = team.adopt_projects_for(new_user)
    except Exception:  # never block sign-up on team bookkeeping
        current_app.logger.exception("Could not apply team state for %s", values["email"])
        claimed = adopted = 0

    if claimed:
        message = (
            "Account created. You are now a build manager on the projects you were "
            "invited to — sign in to open them."
        )
    elif adopted:
        message = (
            "Account created. We found "
            f"{adopted} project{'s' if adopted != 1 else ''} your build manager filed for you — sign in to open them."
        )

    next_url = request.form.get("next") or ""
    if not next_url.startswith("/"):
        next_url = ""

    if web.wants_json():
        return web.ok(
            message,
            open_modal="modal-login",
            modal_notice=message,
        )

    flash(message, "success")
    if next_url:
        return redirect(url_for("auth.login", next=next_url))
    return redirect(url_for("auth.login"))


@bp.post("/logout")
def logout():
    if g.user:
        auth.audit_auth("logout", user_id=g.user["id"])
    auth.logout_user()
    flash("You have signed out.", "success")
    return redirect(url_for("public.landing"))
