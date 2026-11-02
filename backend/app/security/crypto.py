"""个人信息字段加密。格式：1 字节密钥版本 + 12 字节随机 nonce + AES-256-GCM 密文（含认证标签）。"""
from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = 1


class DecryptError(ValueError):
    pass


def encrypt(plaintext: str, key: bytes, *, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return bytes([_VERSION]) + nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)


def decrypt(blob: bytes, key: bytes, *, aad: bytes = b"") -> str:
    if not blob or blob[0] != _VERSION or len(blob) < 1 + 12 + 16:
        raise DecryptError("密文格式或版本不对")
    try:
        return AESGCM(key).decrypt(blob[1:13], blob[13:], aad).decode("utf-8")
    except Exception as exc:  # cryptography.exceptions.InvalidTag
        raise DecryptError("密文被篡改或密钥不对") from exc


def lookup_hash(value: str, key: bytes) -> str:
    """用于按手机号等查找的确定性哈希；不可逆，换密钥后需要重算。"""
    normalized = "".join(value.split())
    return "hmac256:" + hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
