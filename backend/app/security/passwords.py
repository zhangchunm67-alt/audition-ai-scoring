from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()
MIN_LENGTH = 10


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"密码至少 {MIN_LENGTH} 位")
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# 用户不存在时也做一次校验，避免按响应时间猜出用户名
DUMMY_HASH = _ph.hash("dummy-password-for-timing")
