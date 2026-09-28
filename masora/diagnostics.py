"""Diagnostics collected by `masora check`."""

from __future__ import annotations

from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"

E_FRONTMATTER = "E-FRONTMATTER"
E_YAML = "E-YAML"
E_CANON_FLOW = "E-CANON-FLOW"
E_CANON_DUPKEY = "E-CANON-DUPKEY"
E_CANON_ALIAS = "E-CANON-ALIAS"
E_CANON_TAG = "E-CANON-TAG"
E_CANON_QUOTE = "E-CANON-QUOTE"
E_CANON_KEY = "E-CANON-KEY"
E_ULID = "E-ULID"
E_FILENAME = "E-FILENAME"
E_SCHEMA = "E-SCHEMA"
E_VERSION = "E-VERSION"
E_TIMESTAMP = "E-TIMESTAMP"
E_ANCHOR = "E-ANCHOR"
E_PROOFQUERY = "E-PROOFQUERY"
E_SUMMARY = "E-SUMMARY"
E_DUP_ID = "E-DUP-ID"
E_TOMBSTONED = "E-TOMBSTONED"
E_TOMBSTONE_SHAPE = "E-TOMBSTONE-SHAPE"
E_CYCLE = "E-CYCLE"
E_TARGET_KIND = "E-TARGET-KIND"
E_LINEAGE = "E-LINEAGE"
E_REWRITE = "E-REWRITE"
E_GC_UNAVAILABLE = "E-GC-UNAVAILABLE"
E_FOUNDER = "E-FOUNDER"
E_TOMBSTONE_SHRINK = "E-TOMBSTONE-SHRINK"
E_GIT = "E-GIT"
E_NO_ORIGIN = "E-NO-ORIGIN"
E_MERGE_BASE = "E-MERGE-BASE"
W_DANGLING = "W-DANGLING"
W_SKEW = "W-SKEW"
W_FOUNDER = "W-FOUNDER"
W_REPLAY = "W-REPLAY"


@dataclass(frozen=True)
class Diag:
    severity: str
    code: str
    message: str
    path: str | None = None

    def render(self) -> str:
        where = f" {self.path}" if self.path else ""
        return f"{self.severity} {self.code}:{where} {self.message}"


class CheckFailure(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag
