"""Send a test email so an SMTP setup can be proven before it is relied on.

    python -m tools.check_email you@gmail.com

Run it from the repo root with the app's virtualenv. It reads the same
environment (or .env) as the app, prints the resolved settings with the
password masked, sends one real message and explains common failures.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


# Gmail and most providers answer a bad login with 535; a blocked port times
# out instead. Mapping these to plain English saves a lot of guessing.
HINTS = {
    "535": (
        "The provider rejected the username/password. For Gmail this almost "
        "always means you used your normal password: create an App Password "
        "at https://myaccount.google.com/apppasswords (2-Step Verification "
        "must be on) and paste all 16 characters with no spaces."
    ),
    "534": "The provider wants a stronger login method â€” use an App Password.",
    "530": "Authentication is required before sending. Check SMTP_USERNAME.",
    "550": (
        "The From address was refused. SMTP_FROM_EMAIL must be the same "
        "address as SMTP_USERNAME, or an alias verified under 'Send mail as'."
    ),
    "timed out": (
        "The connection timed out. Port 587 often blocked on office and hotel "
        "networks; try SMTP_PORT=465 with SMTP_USE_SSL=1 and SMTP_USE_TLS=0."
    ),
    "certificate": "TLS handshake failed â€” check the system clock and any proxy.",
    "connection unexpectedly closed": (
        "The server accepted the connection then hung up, usually a blocked "
        "outbound SMTP port or a provider that wants 465/SSL instead of 587. "
        "Many hosts (Render, Heroku, some ISPs) block port 25 and 587 â€” try "
        "SMTP_PORT=465, SMTP_USE_SSL=1, SMTP_USE_TLS=0."
    ),
    "connection refused": (
        "Nothing is listening on that host/port. Check SMTP_PORT and whether "
        "the network blocks outbound SMTP."
    ),
}

HINTS["smtpauthenticationerror"] = HINTS["535"]


def explain(error: str) -> str:
    lowered = error.lower()
    for needle, hint in HINTS.items():
        if needle in lowered:
            return hint
    if "name or service not known" in lowered or "getaddrinfo" in lowered:
        return "SMTP_HOST could not be resolved â€” check the spelling."
    return "Check SMTP_HOST, SMTP_PORT and the TLS/SSL flags."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send a YaVaKa test email.")
    parser.add_argument(
        "recipient",
        nargs="?",
        help="Where to send the test. Defaults to SMTP_FROM_EMAIL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved settings and exit without sending.",
    )
    args = parser.parse_args(argv)

    app = create_app()
    config = app.config
    recipient = args.recipient or config.get("SMTP_FROM_EMAIL")

    print("SMTP settings")
    print(f"  host      {config.get('SMTP_HOST') or '(not set)'}")
    print(f"  port      {config.get('SMTP_PORT')}")
    print(f"  starttls  {bool(config.get('SMTP_USE_TLS'))}")
    print(f"  ssl       {bool(config.get('SMTP_USE_SSL'))}")
    print(f"  username  {config.get('SMTP_USERNAME') or '(not set)'}")
    print(f"  password  {_mask(config.get('SMTP_PASSWORD') or '')}")
    print(f"  from      {config.get('SMTP_FROM_EMAIL') or '(not set)'}")
    print(f"  to        {recipient or '(none)'}")

    from notifications import _send_email, email_configured

    with app.app_context():
        configured = email_configured()

    if not configured:
        print(
            "\nEmail is NOT configured: SMTP_HOST and SMTP_FROM_EMAIL must both "
            "be set. See .env.example for a Gmail template."
        )
        return 1

    if not recipient:
        print("\nNo recipient. Pass an address or set SMTP_FROM_EMAIL.")
        return 1

    if args.dry_run:
        print("\nDry run: nothing sent.")
        return 0

    print(f"\nSending to {recipient} ...")
    with app.app_context():
        result = _send_email(
            recipient,
            "YaVaKa test email",
            "This is a test message from your YaVaKa deployment.\n\n"
            "If you can read this, password resets, update notifications and "
            "team invites will reach people.\n",
        )

    if result.get("status") == "sent":
        print("Sent. Check the inbox (and the spam folder for a first send).")
        return 0

    error = result.get("error", "unknown error")
    print(f"Failed: {error}\n{explain(error)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

