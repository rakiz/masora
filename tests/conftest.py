from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, make_verify, write_event


@pytest.fixture
def base(tmp_path) -> Path:
    path = tmp_path / "base"
    path.mkdir()
    return path


@pytest.fixture
def single_claim_base(base) -> Path:
    write_event(base, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    return base


@pytest.fixture
def claimed_base(base) -> Path:
    write_event(base, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000001.verify.md",
        make_verify("01J8Z3K0000000000000000001", ULID_L1, ULID_L1),
    )
    return base
