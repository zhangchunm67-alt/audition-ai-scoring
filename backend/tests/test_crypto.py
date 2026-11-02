import os

import pytest

from app.security.crypto import DecryptError, decrypt, encrypt, lookup_hash
from app.security.passwords import hash_password, verify_password


def test_encrypt_round_trip_and_randomized():
    key = os.urandom(32)
    a, b = encrypt("张三 13800000000", key), encrypt("张三 13800000000", key)
    assert a != b and b"13800000000" not in a
    assert decrypt(a, key) == "张三 13800000000"


def test_tamper_and_wrong_key_detected():
    key = os.urandom(32)
    blob = bytearray(encrypt("李四", key))
    blob[-1] ^= 1
    with pytest.raises(DecryptError):
        decrypt(bytes(blob), key)
    with pytest.raises(DecryptError):
        decrypt(encrypt("李四", key), os.urandom(32))


def test_aad_binds_context():
    key = os.urandom(32)
    blob = encrypt("王五", key, aad=b"candidate:1")
    with pytest.raises(DecryptError):
        decrypt(blob, key, aad=b"candidate:2")


def test_lookup_hash_deterministic_and_normalized():
    key = os.urandom(32)
    assert lookup_hash("138 0000 0000", key) == lookup_hash("13800000000", key)
    assert lookup_hash("13800000000", key) != lookup_hash("13800000000", os.urandom(32))


def test_password_hashing():
    h = hash_password("correct-horse-battery")
    assert verify_password(h, "correct-horse-battery") and not verify_password(h, "nope")
    with pytest.raises(ValueError):
        hash_password("short")


def test_settings_require_keys(monkeypatch):
    from app import settings

    monkeypatch.setenv("APP_DATA_KEY", "c2hvcnQ=")
    settings.get_settings.cache_clear()
    try:
        with pytest.raises(settings.SettingsError):
            settings.get_settings()
        monkeypatch.delenv("APP_DATA_KEY")
        with pytest.raises(settings.SettingsError):
            settings.get_settings()
    finally:
        monkeypatch.undo()
        settings.get_settings.cache_clear()
