"""S1-13 — key separation: independent Fernet encryption key vs OTP HMAC pepper.

Asserts:
  * encryption/decryption round-tripping with a versioned token,
  * migration safety — legacy (unversioned) tokens keyed on sha256(secret_key)
    still decrypt,
  * rotation — tokens minted under an older wallet key still decrypt after the
    active key advances,
  * the OTP pepper is a genuinely distinct key from the Fernet encryption key
    (the original M1 finding).
"""

import base64
import hashlib
import hmac
import secrets

import pytest
from cryptography.fernet import Fernet

from app import security
from app.config import Settings


def _settings(**overrides) -> Settings:
    kwargs = {
        "secret_key": "unit-test-master-secret",
        "env": "test",
        "otp_pepper": None,
        "encryption_keys": [],
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.security.get_settings", lambda: settings)


def _b64_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


# ---------------------------------------------------------------- round trip / versioning
def test_encrypt_decrypt_roundtrip_is_versioned(monkeypatch):
    _patch_settings(monkeypatch, _settings())
    token = security.encrypt_secret("sk-abc-123")
    assert token.startswith("v1."), token
    assert security.decrypt_secret(token) == "sk-abc-123"


def test_empty_value_short_circuits(monkeypatch):
    _patch_settings(monkeypatch, _settings())
    assert security.encrypt_secret("") == ""
    assert security.decrypt_secret("") == ""


def test_password_hashing_unaffected():
    stored = security.hash_password("p@ss")
    assert security.verify_password("p@ss", stored)
    assert not security.verify_password("wrong", stored)


# ---------------------------------------------------------------- migration safety
def test_legacy_unversioned_token_still_decrypts(monkeypatch):
    """Pre-S1-13 ciphertext (no ``vN.`` prefix, key = sha256(secret_key)) must
    keep decrypting so existing stored apiKeys are never stranded."""
    secret = "legacy-secret"
    _patch_settings(monkeypatch, _settings(secret_key=secret))

    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    old_token = Fernet(legacy_key).encrypt(b"old-api-key").decode("ascii")
    assert "v" not in old_token[:2]  # sanity: no version prefix

    assert security.decrypt_secret(old_token) == "old-api-key"


def test_encrypted_output_changes_with_secret_key(monkeypatch):
    _patch_settings(monkeypatch, _settings(secret_key="secret-a"))
    t_a = security.encrypt_secret("same-value")

    _patch_settings(monkeypatch, _settings(secret_key="secret-b"))
    t_b = security.encrypt_secret("same-value")

    assert t_a != t_b  # different master -> different derived key -> different token


# ---------------------------------------------------------------- rotation
def test_rotation_old_token_still_decrypts(monkeypatch):
    k1 = _b64_key()
    k2 = _b64_key()

    # Historic wallet: only k1 known, active = v1.
    wallet_v1 = security._build_wallet(_settings(encryption_keys=[k1]))
    old_token = wallet_v1.encrypt(b"rotate-me")
    assert old_token.startswith("v1.")

    # After rotation: k2 becomes active (v2); k1 retained for decryption.
    _patch_settings(monkeypatch, _settings(encryption_keys=[k1, k2]))
    assert security.decrypt_secret(old_token) == "rotate-me"
    assert security.encrypt_secret("rotate-me").startswith("v2.")


def test_unknown_version_returns_empty(monkeypatch):
    _patch_settings(monkeypatch, _settings(encryption_keys=[_b64_key()]))
    assert security.decrypt_secret("v99.abc") == ""


def test_malformed_key_fails_loudly():
    with pytest.raises(ValueError):
        security._decode_fernet_key("not-valid-base64!!")


# ---------------------------------------------------------------- key separation (M1)
def test_otp_pepper_is_distinct_from_fernet_key():
    """The two purposes must never share key material (the original finding)."""
    master = b"unit-test-master-secret"
    fernet_key = security._hkdf(master, security._FERNET_INFO)
    otp_pepper = security._hkdf(master, security._OTP_PEPPER_INFO)
    legacy_key = security._legacy_fernet_key("unit-test-master-secret")

    assert fernet_key != otp_pepper
    assert fernet_key != legacy_key
    assert otp_pepper != legacy_key


def test_otp_hmac_deterministic_and_scoped(monkeypatch):
    _patch_settings(monkeypatch, _settings())
    default = security.otp_hmac("123456")
    assert default == security.otp_hmac("123456")
    assert default != security.otp_hmac("654321")

    # A different explicit pepper yields a different HMAC for the same code.
    _patch_settings(monkeypatch, _settings(otp_pepper="some-other-pepper"))
    assert security.otp_hmac("123456") != default


def test_explicit_otp_pepper_is_used(monkeypatch):
    _patch_settings(monkeypatch, _settings(otp_pepper="explicit-pepper"))
    expected = hmac.new(b"explicit-pepper", b"123456", hashlib.sha256).hexdigest()
    assert security.otp_hmac("123456") == expected
