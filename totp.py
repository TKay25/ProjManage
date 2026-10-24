"""Time-based one-time passwords (RFC 6238) and recovery codes.

Standard library only, so two-factor authentication works on any host without
adding a dependency. Secrets are base32 (what every authenticator app expects)
and recovery codes are stored as SHA-256 hashes, never in the clear.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_secret(byte_length: int = 20) -> str:
    """A new base32 secret, unpadded because apps add the padding back."""
    return base64.b32encode(secrets.token_bytes(byte_length)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = "".join(ch for ch in (secret or "").upper() if ch not in " -")
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding)


def code_at(secret: str, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def current_code(secret: str, at: float | None = None, digits: int = DIGITS) -> str:
    moment = time.time() if at is None else at
    return code_at(secret, int(moment // PERIOD), digits)


def verify(secret: str, code: str, *, window: int = 1, at: float | None = None) -> bool:
    """True when ``code`` matches now, or one step either side for clock drift."""
    supplied = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(supplied) != DIGITS or not secret:
        return False

    moment = time.time() if at is None else at
    step = int(moment // PERIOD)
    matched = False
    for drift in range(-window, window + 1):
        if hmac.compare_digest(code_at(secret, step + drift), supplied):
            matched = True
    return matched


def provisioning_uri(secret: str, account: str, issuer: str = "YaVaKa") -> str:
    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Human-copyable codes in two groups of four, e.g. ``k7md-2xqp``."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_code(code: str) -> str:
    normalised = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
