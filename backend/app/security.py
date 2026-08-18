"""Small security helpers for v0.1.

- apiKey encryption: Fernet (symmetric) keyed from the app secret so stored AI
  provider keys are never plaintext. Decrypted only in-process when needed.
- tenant slug generation from a display name (unique suffix) — slug is NOT part
  of the API surface (PO decision) but serves as the tenant unique identifier.
"""

import base64
import hashlib
import re
import unicodedata

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

# slugify supports Persian/Arabic letters + Latin alnum; keeps "fa-IR" style okay.
_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_HYPHEN = re.compile(r"[-\s]+")


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


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
