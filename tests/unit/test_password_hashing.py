from __future__ import annotations

import pytest

from pipelines.minimal_slice.password_hashing import (
    hash_password,
    password_hash_needs_rehash,
    verify_password,
)


def test_hash_password_and_verify_round_trip() -> None:
    password = "S3curePassw0rd!"
    password_hash = hash_password(password)

    assert password_hash
    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong-password", password_hash) is False
    assert password_hash_needs_rehash(password_hash) is False


def test_hash_password_rejects_short_password() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        hash_password("short")

