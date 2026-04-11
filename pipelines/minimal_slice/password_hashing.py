from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 512


def validate_password_input(password: str) -> None:
    if not isinstance(password, str):
        raise ValueError("password is required.")
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be no more than {_MAX_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    validate_password_input(password)
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bool(_HASHER.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_hash_needs_rehash(password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bool(_HASHER.check_needs_rehash(password_hash))
    except InvalidHashError:
        return False

