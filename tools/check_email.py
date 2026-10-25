"""Send a test email so an email setup can be proven before it is relied on.

    python -m tools.check_email you@gmail.com
    python -m tools.check_email you@gmail.com --dry-run

Run it from the repo root with the app's virtualenv. It reads the same
environment (or .env) as the app, prints the resolved settings with secrets
masked, sends one real message and translates common failures into a next step.
"""

import argparse
import json
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


# A wrong login answers 535 (SMTP) or 401 (HTTPS API); a blocked port closes
# the socket instead. Naming the cause saves a lot of guessing.
HINTS = {
    "535": (
        "The provider rejected the username/password. For Gmail this almost "
        "always means you used your normal password: create an App Password "
        "at https://myaccount.google.com/apppasswords (2-Step Verification "
        "must be on) and paste all 16 characters with no spaces."
    ),
    "534": "The provider wants a stronger login method - use an App Password.",
    "530": "Authentication is required before sending. Check SMTP_USERNAME.",
    "550": (
        "The From address was refused. The sender must be the address you "
        "authenticated as, or an alias verified with the provider."
    ),
    "timed out": (
        "The connection timed out. Port 587 is blocked on many hosts and "
        "office networks. Either use SMTP_PORT=465 with SMTP_USE_SSL=1 and "
        "SMTP_USE_TLS=0, or switch to an HTTPS email API (see README)."
    ),
    "certificate": "TLS handshake failed - check the system clock and any proxy.",
    "connection unexpectedly closed": (
        "The server accepted the connection then hung up, which is what a "
        "blocked outbound SMTP port looks like. Render Free blocks 25, 465 "
        "and 587 entirely: use an HTTPS API key (BREVO_API_KEY, RESEND_API_KEY "
        "or SENDGRID_API_KEY) instead of SMTP."
    ),
    "connection refused": (
        "Nothing is listening on that host/port. Check SMTP_PORT and whether "
        "the network blocks outbound SMTP."
    ),
}

API_HINTS = {
    "401": (
        "The API key was rejected. Copy it again from the provider dashboard "
        "and make sure it has send permission."
    ),
    "403": (
        "The key is valid but this sender is not allowed. Verify the address "
        "(or the whole domain) in the provider dashboard - Brevo and SendGrid "
        "call this 'sender verification', Resend requires a verified domain."
    ),
    "422": "The request was rejected - check EMAIL_FROM is a real address.",
    "429": "Daily quota or rate limit reached. Try tomorrow or upgrade.",
    "400": "The provider rejected the payload; check the from address.",
}

HINTS["smtpauthenticationerror"] = HINTS["535"]


def explain(error: str) -> str:
    lowered = error.lower()
    for needle, hint in API_HINTS.items():
        # API errors are reported as "<code> <body>", so match the leading code.
        if lowered.startswith(needle + " "):
            return hint
    for needle, hint in HINTS.items():
        if needle in lowered:
            return hint
    if "name or service not known" in lowered or "getaddrinfo" in lowered:
        return "SMTP_HOST could not be resolved - check the spelling."
    return "Check the provider settings above."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send a YaVaKa test email.")
    parser.add_argument(
        "recipient",
        nargs="?",
        help="Where to send the test. Defaults to EMAIL_FROM.",
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

    from notifications import (
        API_PROVIDERS,
        _api_request,
        _send_email,
        api_provider,
        email_configured,
    )

    with app.app_context():
        provider = api_provider()
        configured = email_configured()

    if provider:
        key_setting, url = API_PROVIDERS[provider]
        print(f"Email provider: {provider} (HTTPS API)")
        print(f"  endpoint  {url}")
        print(f"  api key   {_mask(config.get(key_setting) or '')}")
    else:
        print("Email provider: SMTP")
        print(f"  host      {config.get('SMTP_HOST') or '(not set)'}")
        print(f"  port      {config.get('SMTP_PORT')}")
        print(f"  starttls  {bool(config.get('SMTP_USE_TLS'))}")
        print(f"  ssl       {bool(config.get('SMTP_USE_SSL'))}")
        print(f"  username  {config.get('SMTP_USERNAME') or '(not set)'}")
        print(f"  password  {_mask(config.get('SMTP_PASSWORD') or '')}")

    print(f"  from      {config.get('SMTP_FROM_EMAIL') or '(not set)'}")
    print(f"  to        {recipient or '(none)'}")

    if not configured:
        print(
            "\nEmail is NOT configured. Set either an HTTPS API key "
            "(BREVO_API_KEY, RESEND_API_KEY or SENDGRID_API_KEY) or "
            "SMTP_HOST, plus a sender address. See .env.example."
        )
        return 1

    if not recipient:
        print("\nNo recipient. Pass an address or set EMAIL_FROM.")
        return 1

    if args.dry_run:
        if provider:
            with app.app_context():
                _, headers, payload = _api_request(
                    provider, recipient, "YaVaKa test email", "..."
                )
            redacted = {
                key: ("***" if "authorization" in key.lower() or "api-key" in key.lower() else value)
                for key, value in headers.items()
            }
            print("\nHeaders:", json.dumps(redacted, indent=2, sort_keys=True))
            print("Payload:", json.dumps(payload, indent=2, sort_keys=True))
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
