import pytest

from masora.ulid import UlidError, encode_ulid, is_ulid, new_ulid, validate_ulid

VALID = "01J8Z3K0000000000000000000"


def test_accepts_canonical_uppercase():
    assert validate_ulid(VALID) == VALID
    assert is_ulid(VALID)


@pytest.mark.parametrize(
    "value",
    [
        "01J8Z3K000000000000000000",
        "01J8Z3K00000000000000000000",
        "01j8z3k0000000000000000000",
        "01J8Z3K000000000000000000O",
        "01J8Z3K000000000000000000I",
        "01J8Z3K000000000000000000L",
        "01J8Z3K000000000000000000U",
        "81J8Z3K0000000000000000000",
        "",
        "01J8Z3K00000000000000000 0",
    ],
)
def test_rejects_malformed(value):
    with pytest.raises(UlidError):
        validate_ulid(value)


def test_rejects_non_string():
    with pytest.raises(UlidError):
        validate_ulid(123)


def test_first_character_must_be_at_most_seven():
    assert validate_ulid("7" + "F" * 25)
    with pytest.raises(UlidError):
        validate_ulid("8" + "0" * 25)


def test_roundtrip_encode():
    assert encode_ulid(0, 0) == "0" * 26
    encoded = encode_ulid(2**48 - 1, 2**80 - 1)
    assert len(encoded) == 26
    assert encoded[0] == "7"


def test_new_ulid_is_valid_and_monotonic_within_process():
    seen = [new_ulid() for _ in range(1000)]
    for value in seen:
        assert is_ulid(value)
    assert seen == sorted(seen)
    assert len(set(seen)) == 1000
