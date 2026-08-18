"""Small security helpers for v0.1.

- apiKey encryption: Fernet (symmetric) keyed from the app secret so stored AI
  provider keys are never plaintext. Decrypted only in-process when needed.
- tenant slug generation from a display name (unique suffix) — slug is NOT part
  of the API surface (PO decision) but serves as the tenant unique identifier.
"""

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

# slugify supports Persian/Arabic letters + Latin alnum; keeps "fa-IR" style okay.
_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_HYPHEN = re.compile(r"[-\s]+")


def _secret_digest() -> bytes:
    return hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_secret_digest()))


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def slugify(text: str, *, max_len: int = 32) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = _SLUG_STRIP.sub("", text)
    text = _SLUG_HYPHEN.sub("-", text).strip("-")
    return text[:max_len]


# ---------------------------------------------------------------- passwords (stdlib only)
# OWASP-recommended iteration count for PBKDF2-HMAC-SHA256 (≥ 600k as of 2023).
_PBKDF2_ALGO = "sha256"
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16


def hash_password(plain: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random 16-byte salt, encoded as ``pbkdf2_sha256$salt$hash``."""
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, plain.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${salt.hex()}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time verify against a ``hash_password`` value. False on any malformed input."""
    try:
        algo, salt_hex, hash_hex = stored.split("$", 2)
    except (ValueError, AttributeError):
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------- sessions / hashing
def new_session_token() -> str:
    """URL-safe 256-bit random session token (raw value; only its SHA-256 hash is stored)."""
    return secrets.token_urlsafe(32)


def sha256(raw: str) -> str:
    """SHA-256 hex digest — used for onboarding tokens and session tokens."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def otp_hmac(code: str) -> str:
    """Keyed-HMAC of a 6-digit OTP using the server secret as pepper.

    Storing this instead of a plain SHA-256 means a DB leak alone does NOT reveal
    the codes; the server-side secret is required to reconstruct them. Combined
    with the short TTL + max-attempts rate limit this hardens the 1M-code space.
    """
    return hmac.new(_secret_digest(), code.encode("utf-8"), hashlib.sha256).hexdigest()
