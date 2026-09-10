"""Password hashing and opaque session tokens (US-002 security requirements).

- Passwords: Argon2id via argon2-cffi (US-002 allows Argon2 or BCrypt).
- Sessions: 48-byte URL-safe token; only its SHA-256 hex digest is stored
  (sessions.token_hash, migration 0002).
"""

import hashlib
import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# US-002 (PO feedback 2026-08-18): only Latin symbols count toward the
# "one symbol" rule; Persian characters are not symbols.
LATIN_SYMBOLS = set(string.punctuation)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def password_policy_violations(password: str) -> list[str]:
    """Return the violated rule codes for the US-002 password policy."""
    violations: list[str] = []
    if len(password) < 8:
        violations.append("MIN_LENGTH")
    if not any(ch.isupper() for ch in password):
        violations.append("UPPERCASE")
    if not any(ch.islower() for ch in password):
        violations.append("LOWERCASE")
    if not any(ch.isdigit() for ch in password):
        violations.append("DIGIT")
    if not any(ch in LATIN_SYMBOLS for ch in password):
        violations.append("LATIN_SYMBOL")
    return violations


def new_session_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex) - only the digest is persisted."""
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()
