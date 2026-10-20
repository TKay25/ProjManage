"""Application configuration for Vaka."""

import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _secret_key() -> str:
    """Use SECRET_KEY from the environment, or persist a generated one."""
    env_value = os.environ.get("SECRET_KEY")
    if env_value:
        return env_value

    key_file = INSTANCE_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    return key_file.read_text(encoding="utf-8").strip()


class Config:
    SECRET_KEY = _secret_key()

    DATABASE = os.environ.get("DATABASE_FILE", str(INSTANCE_DIR / "vaka.db"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads"))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024

    SESSION_COOKIE_NAME = "vaka_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Demo data ships sample projects *and* accounts with published passwords,
    # so it must be opted into explicitly. Never default this to true.
    SEED_DEMO = os.environ.get("SEED_DEMO", "false").lower() in {"true", "1", "yes"}
    DEMO_MODE = SEED_DEMO

    # Render (and most PaaS) terminate TLS at the proxy.
    TRUST_PROXY = os.environ.get("TRUST_PROXY", "1") == "1"

    # Templates re-render from disk so edits show up without a restart.
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0

    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    # No default: webhook verification fails closed until the environment sets it.
    WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")

    APP_NAME = "Vaka"
    APP_TAGLINE = "Build from anywhere"
