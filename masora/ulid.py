"""ULID parsing, validation and generation (128-bit Crockford base32, FORMAT.md §3)."""

from __future__ import annotations

import os
import threading
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ENCODE = {c: i for i, c in enumerate(ALPHABET)}
ULID_LENGTH = 26
_TIME_BITS = 48
_TIME_MASK = (1 << _TIME_BITS) - 1
_MAX_RANDOM = (1 << 80) - 1

_lock = threading.Lock()
_last_time = -1
_last_random = -1


class UlidError(ValueError):
    pass


def validate_ulid(value: object, *, what: str = "ULID") -> str:
    if not isinstance(value, str):
        raise UlidError(f"{what} must be a quoted string, got {type(value).__name__}")
    if len(value) != ULID_LENGTH:
        raise UlidError(f"{what} must be {ULID_LENGTH} characters, got {len(value)}: {value!r}")
    if value != value.upper() or any(c.islower() for c in value):
        raise UlidError(f"{what} must be canonical uppercase: {value!r}")
    for c in value:
        if c not in _ENCODE:
            raise UlidError(f"{what} contains non-Crockford-base32 character {c!r}: {value!r}")
    if value[0] not in "01234567":
        raise UlidError(f"{what} exceeds 128 bits (first character must be <= '7'): {value!r}")
    return value


def is_ulid(value: object) -> bool:
    try:
        validate_ulid(value)
    except UlidError:
        return False
    return True


def new_ulid() -> str:
    global _last_time, _last_random
    with _lock:
        time_ms = time.time_ns() // 1_000_000
        if time_ms == _last_time:
            random = _last_random + 1
            if random > _MAX_RANDOM:
                time_ms += 1
                random = int.from_bytes(os.urandom(10), "big")
        else:
            random = int.from_bytes(os.urandom(10), "big")
        _last_time = time_ms
        _last_random = random
        return encode_ulid(time_ms, random)


def encode_ulid(time_ms: int, random: int) -> str:
    if not 0 <= time_ms <= _TIME_MASK:
        raise UlidError(f"timestamp out of 48-bit range: {time_ms}")
    if not 0 <= random <= _MAX_RANDOM:
        raise UlidError(f"randomness out of 80-bit range: {random}")
    value = (time_ms << 80) | random
    chars = []
    for shift in range(25, -1, -1):
        chars.append(ALPHABET[(value >> (5 * shift)) & 31])
    return "".join(chars)
