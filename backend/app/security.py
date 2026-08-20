"""Security helpers: apiKey Fernet encryption + OTP HMAC pepper (key-separated).

Key separation (S1-13, Security Standards v1.0 §Secrets Management + ADR-008):

  Previously a single ``secret_key`` was hashed once (``sha256``) and reused for
  BOTH the Fernet apiKey-encryption key *and* the OTP HMAC pepper. A compromise
  of one purpose therefore implicitly exposed the other. We now:

    * derive domain-separated subkeys per purpose via HKDF-SHA256, and
    * keep a versioned **key wallet** for the encryption key so it can rotate
      independently without orphaning existing ciphertext.

Wallet / versioning
  ``encrypt_secret`` writes ``v<version>.<fernet_token>`` using the active
  (highest-version) key; ``decrypt_secret`` reads the version prefix and picks
  the matching key. Legacy tokens (pre-S1-13) carry no prefix and are decrypted
  with version 0 — the original ``sha256(secret_key)`` key — so previously stored
  apiKeys keep decrypting unmodified (migration-safe).

OTP pepper
  ``otp_hmac`` uses an independent pepper: ``OTP_PEPPER`` when set (required
  outside dev/test), else an HKDF subkey under a distinct purpose label so it
  never coincides with the Fernet key material.
"""

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings

# slugify supports Persian/Arabic letters + Latin alnum; keeps "fa-IR" style okay.
_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_HYPHEN = re.compile(r"[-\s]+")

# ---------------------------------------------------------------- key separation
_FERNET_KEY_BYTES = 32  # Fernet requires exactly 32 bytes of key material.

# Legacy (pre-S1-13) version: no token prefix, key = sha256(secret_key).
_LEGACY_VERSION = 0

# Versioned token layout: "v<version>.<urlsafe-b64 fernt token>". Fernet tokens
# are [A-Za-z0-9_-] plus optional padding, never contain '.', so the prefix is
# unambiguous and cannot collide with the payload.
_VERSIONED_TOKEN = re.compile(r"^v(\d+)\.([A-Za-z0-9_\-=]+)$")

# HKDF purpose labels guarantee distinct keys for distinct purposes even when
# both are ultimately derived from the same master secret.
_FERNET_INFO = b"hiveos/v1/apiKey/fernet"
_OTP_PEPPER_INFO = b"hiveos/v1/otp/pepper"


def _hkdf(master: bytes, info: bytes, length: int = _FERNET_KEY_BYTES) -> bytes:
    """HKDF-SHA256 (RFC 5869) subkey derivation for domain separation.

    ``info`` labels the purpose so several independent keys can be carved out of
    one master secret without ever coinciding. Deterministic per (master, info).
    Empty salt (the master is already a high-entropy secret, not a password).
    """
    prk = hmac.new(b"", master, hashlib.sha256).digest()  # extract
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _legacy_fernet_key(secret_key: str) -> bytes:
    """Version-0 encryption key — kept byte-for-byte identical to pre-S1-13 so
    existing stored apiKeys decrypt unchanged (migration safety)."""
    return hashlib.sha256(secret_key.encode("utf-8")).digest()


def _decode_fernet_key(b64: str) -> bytes:
    """Validate a configured base64(32-byte) Fernet key; fail loudly if malformed."""
    try:
        raw = base64.urlsafe_b64decode(b64.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 — normalize to a clear config error
        raise ValueError(f"encryption key is not valid url-safe base64: {exc!r}") from exc
    if len(raw) != _FERNET_KEY_BYTES:
        raise ValueError(
            f"encryption key must decode to {_FERNET_KEY_BYTES} bytes, got {len(raw)}"
        )
    return raw


class _KeyWallet:
    """Versioned set of Fernet encryption keys with rotation support.

    The highest version is the *active* key used for new encryption; every other
    version is retained purely for decryption, so rotating (replacing) the active
    key never strands ciphertext written under an older key.
    """

    def __init__(self, keys: dict[int, bytes]) -> None:
        if not keys:
            raise ValueError("encryption key wallet must not be empty")
        for version, key in keys.items():
            if len(key) != _FERNET_KEY_BYTES:
                raise ValueError(
                    f"version {version} key is {len(key)} bytes, expected {_FERNET_KEY_BYTES}"
                )
        self._keys = dict(keys)
        self._active_version = max(keys)

    @property
    def active_version(self) -> int:
        return self._active_version

    def key_bytes(self, version: int) -> bytes:
        return self._keys[version]

    def _fernet(self, version: int) -> Fernet:
        key = self._keys.get(version)
        if key is None:
            raise InvalidToken  # unknown version -> treat as undecryptable
        return Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plaintext: bytes) -> str:
        token = self._fernet(self._active_version).encrypt(plaintext).decode("ascii")
        return f"v{self._active_version}.{token}"

    def decrypt(self, token: str) -> bytes:
        match = _VERSIONED_TOKEN.fullmatch(token)
        if match:
            version = int(match.group(1))
            payload = match.group(2)
        else:
            version = _LEGACY_VERSION  # pre-separation token (no prefix)
            payload = token
        return self._fernet(version).decrypt(payload.encode("ascii"))


def _build_wallet(settings: Settings) -> _KeyWallet:
    """Assemble the encryption key wallet from settings.

    Version 0 is always the legacy ``sha256(secret_key)`` key for back-compat
    decryption. Versioned keys come from ``encryption_keys`` (a JSON list of
    base64 32-byte keys, oldest-first, last = active). When none is configured
    (dev/test), a single domain-separated subkey is derived.
    """
    keys: dict[int, bytes] = {_LEGACY_VERSION: _legacy_fernet_key(settings.secret_key)}
    configured = settings.encryption_keys or []
    if configured:
        for version, b64 in enumerate(configured, start=1):
            keys[version] = _decode_fernet_key(b64)
    else:
        keys[1] = _hkdf(settings.secret_key.encode("utf-8"), _FERNET_INFO)
    return _KeyWallet(keys)


def _otp_pepper(settings: Settings) -> bytes:
    if settings.otp_pepper:
        return settings.otp_pepper.encode("utf-8")
    return _hkdf(settings.secret_key.encode("utf-8"), _OTP_PEPPER_INFO)


# ---------------------------------------------------------------- apiKey encryption
def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _build_wallet(get_settings()).encrypt(value.encode("utf-8"))


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _build_wallet(get_settings()).decrypt(token).decode("utf-8")
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
    """Keyed-HMAC of a 6-digit OTP using the OTP pepper (independent of Fernet).

    Storing this instead of a plain SHA-256 means a DB leak alone does NOT reveal
    the codes; the server-side pepper is required to reconstruct them. Combined
    with the short TTL + max-attempts rate limit this hardens the 1M-code space.
    """
    return hmac.new(_otp_pepper(get_settings()), code.encode("utf-8"), hashlib.sha256).hexdigest()
