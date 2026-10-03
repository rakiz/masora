"""Shared MCP write path: base resolution, canonical emission, atomic write + post-check.

One pipeline for all write tools (FORMAT.md §4-§6): resolve the base per
MASORA_DESIGN.md §8-§9 (mapping on the normalized code remote, else
`default_base`, else explicit), emit the event file in the canonical block
style of FORMAT.md §4, pre-validate with `schema.validate_event`, refuse
high-confidence credential shapes in the content fields (E-WRITE-SECRET —
secrets belong in a secret manager, never in a Masora base), write, then
re-run `check_base` — a tool that returns success on an invalid tree is
forbidden, so a failed post-check unlinks the just-written file (FORMAT.md §6:
nothing is written).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from . import config
from .checker import (
    ALLOWED_TARGET_KINDS,
    CheckResult,
    _parse_event_file,
    check_base,
)
from .diagnostics import (
    E_ANCHOR,
    E_DUP_ID,
    E_LINEAGE,
    E_MCP_NO_BASE,
    E_TARGET_KIND,
    E_TOMBSTONED,
    E_WRITE_SECRET,
    W_DANGLING,
    W_REPLAY,
    W_SKEW,
    CheckFailure,
    Diag,
)
from .index import ParsedEvent, _parse_events
from .schema import SHA_RE, EventRecord, validate_event
from .sync import git_env, run_git


class WriteError(Exception):
    """A refused tool operation carrying its diagnostics (the first code leads)."""

    def __init__(self, *diags: Diag):
        super().__init__(diags[0].message if diags else "write refused")
        self.diags = list(diags)

    @property
    def code(self) -> str | None:
        return self.diags[0].code if self.diags else None


def load_user_config() -> dict:
    path = config.config_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise WriteError(
            Diag("error", E_MCP_NO_BASE, f"config.toml cannot be read: {exc}", str(path))
        ) from exc
    return data if isinstance(data, dict) else {}


def origin_remote(repo: Path) -> str | None:
    """The code repo's `origin` URL, or None (git spawns sanitized by `git_env`,
    timeout- and missing-binary-safe)."""
    proc = run_git(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    value = proc.stdout.strip() if proc is not None else ""
    return value if value else None


def origin_state(repo: Path) -> tuple[str, str | None]:
    """(kind, remote) for the no-base diagnostic, never for resolution: kind is
    `not_git_worktree` (the path is not inside a git worktree),
    `git_without_origin` (a worktree whose origin is missing or unreadable) or
    `origin` (readable)."""
    proc = run_git(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        return "not_git_worktree", None
    remote = origin_remote(repo)
    if remote is None:
        return "git_without_origin", None
    return "origin", remote


def human_name(base_dir: Path) -> str | None:
    """The base repo's `git config user.name` — the human writer's self-signed name.

    Declarative provenance (MASORA_DESIGN.md §12.10): identity comes from the
    base-repo git config (the commits are the trust path); None when unset —
    the field is then simply absent from the event.
    """
    proc = run_git(
        ["git", "-C", str(base_dir), "config", "user.name"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    value = proc.stdout.strip() if proc is not None else ""
    return value if value else None


# The `lines` fork-point stamp (FORMAT.md §4) captures a FIXED ref set: the
# HEAD's upstream and the repo's default branch — never a clone-wide scan.
def _default_branch_ref(repo_root: Path) -> str | None:
    """The default branch as a full remote-tracking refname
    (`refs/remotes/origin/HEAD`'s target), or None."""
    proc = run_git(
        ["git", "-C", str(repo_root), "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    ref = proc.stdout.strip() if proc is not None else ""
    return ref if ref else None


def _upstream_ref(repo_root: Path) -> str | None:
    """The current branch's upstream as a full refname, or None (detached HEAD,
    no upstream, any git failure)."""
    proc = run_git(
        ["git", "-C", str(repo_root), "rev-parse", "--symbolic-full-name", "@{upstream}"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    ref = proc.stdout.strip() if proc is not None else ""
    return ref if ref.startswith("refs/") else None


def capture_lines(repo_root: Path, head: str) -> dict[str, str] | None:
    """Tool-captured fork-point stamp (FORMAT.md §4): per ref of the FIXED
    capture set, `git merge-base <head> <ref>` — the squash-proof record of
    where this event's state diverged from each line.

    There is deliberately NO agent-facing argument for this: the write path
    calls it itself (MASORA_DESIGN.md §12.16(m) — never an agent argument,
    never backfilled; absence IS the unknown value). The capture set is FIXED,
    never a clone-wide scan: the HEAD's upstream and the repo's default branch
    (`origin/HEAD`), deduplicated. A ref whose merge-base fails (missing ref,
    unrelated history, any git error) is omitted silently; no successful
    merge-base at all → None, and the caller omits `lines` entirely. Never
    raises: a stamp is captured context, and a failed capture must not block
    a write.
    """
    refs: list[str] = []
    for ref in (_upstream_ref(repo_root), _default_branch_ref(repo_root)):
        if ref is not None and ref not in refs:
            refs.append(ref)
    lines: dict[str, str] = {}
    for ref in refs:
        merge = run_git(
            ["git", "-C", str(repo_root), "merge-base", head, ref],
            capture_output=True,
            text=True,
            env=git_env(),
        )
        sha = merge.stdout.strip() if merge is not None else ""
        if SHA_RE.match(sha):
            short = ref.removeprefix("refs/heads/").removeprefix("refs/remotes/")
            if short:
                lines[short] = sha
    return lines or None


def base_dir_for_name(data: dict, name: str) -> Path | None:
    """`[bases.<name>]` entry → local checkout path (MASORA_DESIGN.md §9 layout)."""
    bases = data.get("bases")
    entry = bases.get(name) if isinstance(bases, dict) else None
    if not isinstance(entry, dict):
        return None
    path = config.bases_root() / name
    sub = entry.get("path")
    if isinstance(sub, str) and sub:
        path = path.joinpath(*PurePosixPath(sub).parts)
    return path


def auto_base(repo_root: Path | None) -> Path | None:
    """Mapping match on the code remote, then `default_base` (MASORA_DESIGN.md §9).

    None when nothing matches; WriteError when the config is unreadable, a
    MATCHED base's checkout is missing, or a MATCHED mapping names no usable
    base — matched-but-broken is never silently skipped. Shared by the MCP
    write tools and the read-only `masora facts`.
    """
    data = load_user_config()
    remote = origin_remote(repo_root) if repo_root is not None else None
    if remote is not None:
        mappings = data.get("mappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                if not isinstance(mapping, dict):
                    continue
                code_remote = mapping.get("code_remote")
                if not isinstance(code_remote, str):
                    continue
                if config.normalize_remote(code_remote) != config.normalize_remote(remote):
                    continue
                bases = mapping.get("bases")
                name = (
                    bases[0]
                    if isinstance(bases, list) and bases and isinstance(bases[0], str)
                    else None
                )
                if name is None:
                    # A mapping whose code_remote MATCHED but that names no usable
                    # base is a broken config, never a silent fall-through to the
                    # next mapping or default_base — writing onto the wrong base
                    # is the one outcome this must never allow (LOW sweep).
                    raise WriteError(
                        Diag(
                            "error",
                            E_MCP_NO_BASE,
                            f"mapping {code_remote!r} matches this repo's origin but names no base"
                            " (its 'bases' is missing, empty or not a list of names) — fix"
                            " config.toml or pass the base parameter explicitly"
                            " (MASORA_DESIGN.md §9)",
                            str(config.config_path()),
                        )
                    )
                path = base_dir_for_name(data, name)
                if path is None or not path.is_dir():
                    raise WriteError(
                        Diag(
                            "error",
                            E_MCP_NO_BASE,
                            f"mapping {code_remote!r} resolves to base '{name}' but {path} does"
                            " not exist (MASORA_DESIGN.md §9)",
                            str(path or config.bases_root() / name),
                        )
                    )
                return path
    default = data.get("default_base")
    if isinstance(default, str) and default:
        path = base_dir_for_name(data, default)
        if path is not None and path.is_dir():
            return path
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                f"default_base '{default}' is not an existing base directory (MASORA_DESIGN.md §9)",
                str(path or config.bases_root() / default),
            )
        )
    return None


def resolve_base(repo_root: Path | None, base: str | None) -> Path:
    """Explicit base first, then `auto_base` (§8-§9).

    A caller-provided base always wins; an unmatched base is never guessed:
    the `E-MCP-NO-BASE` refusal states the remedy for its cause — an omitted
    `repo_root` asks for the repo, a non-worktree root says so, an
    origin-less checkout says mapping resolution is unavailable, an unmapped
    repo asks for `masora setup` or an explicit base. The cause detection
    never affects a resolving call: an origin-less checkout with a valid
    `default_base` or explicit base succeeds.
    """
    if base is not None:
        explicit = Path(base)
        if explicit.is_dir():
            return explicit
        named = base_dir_for_name(load_user_config(), base)
        if named is not None and named.is_dir():
            return named
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                f"base {base!r} is neither an existing directory nor a configured base",
            )
        )
    matched = auto_base(repo_root)
    if matched is not None:
        return matched
    if repo_root is None:
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                "no base resolved: no repo_root was passed — pass repo_root (the checkout you are"
                " asking about) — the base is resolved from that repo's origin remote"
                " (MASORA_DESIGN.md §9)",
            )
        )
    kind, _remote = origin_state(repo_root)
    if kind == "not_git_worktree":
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                "no base resolved: repo_root is not a Git checkout — pass the code checkout itself"
                " (not its workspace parent), or pass base explicitly (MASORA_DESIGN.md §9)",
            )
        )
    if kind == "git_without_origin":
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                "no base resolved: the checkout has no readable origin, so mapping-based resolution"
                " is unavailable — configure origin, configure default_base, or pass base explicitly"
                " (MASORA_DESIGN.md §9)",
            )
        )
    raise WriteError(
        Diag(
            "error",
            E_MCP_NO_BASE,
            "no base resolved: the code repo matches no [[mappings]] entry and no default_base is"
            " configured — run masora setup --base <url> in this checkout, or pass the base"
            " parameter explicitly (MASORA_DESIGN.md §9)",
        )
    )


def checked(base_dir: Path) -> CheckResult:
    """ONE shared full-base validation pass for a write operation (M3).

    Callers that need the base state before writing (the MCP write tools:
    fold envelopes for target resolution, id/tombstone sets for the
    incremental post-check) run this once and thread the result through
    `envelopes`/`write_and_check` instead of re-running `check_base` per
    step. Raises WriteError when the base already fails `check`.
    """
    result = check_base(base_dir)
    if result.errors:
        raise WriteError(*result.errors)
    return result


def records(base_dir: Path) -> dict[str, ParsedEvent]:
    """Validated event records by id (unparsable files are skipped — `check` reports them)."""
    return {pe.record.id: pe for pe in _parse_events(base_dir, [])}


def envelopes(base_dir: Path, shared: CheckResult | None = None) -> dict[str, dict]:
    """Fold envelopes by lineage; a base that already fails `check` is refused.

    `shared` (a `checked()` result) reuses one full pass instead of
    re-validating the whole base (M3).
    """
    result = shared if shared is not None else check_base(base_dir)
    if result.errors:
        raise WriteError(*result.errors)
    return {envelope["lineage"]: envelope for envelope in result.envelopes}


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Non-string scalars round-trip as YAML numbers, never as stringified
        # text (a float 1.5 must come back as 1.5, not "1.5").
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def emit_event(data: dict, indent: int = 0, parent_key: str | None = None) -> str:
    """Canonical block-style YAML (FORMAT.md §4): plain keys, quoted values,
    quoted identity keys under `snapshots`/`neighbours`/`lines`."""
    pad = "  " * indent
    identity_keys = parent_key in ("neighbours", "snapshots", "lines")
    lines = []
    for key, item in data.items():
        key_text = _scalar(key) if identity_keys else str(key)
        if isinstance(item, dict):
            if item:
                lines.append(f"{pad}{key_text}:")
                lines.append(emit_event(item, indent + 1, key))
            else:
                lines.append(f"{pad}{key_text}: {{}}")
        elif isinstance(item, list):
            if item:
                lines.append(f"{pad}{key_text}:")
                lines.append(_emit_list(item, indent + 1, key))
            else:
                lines.append(f"{pad}{key_text}: []")
        else:
            lines.append(f"{pad}{key_text}: {_scalar(item)}")
    return "\n".join(lines)


def _emit_list(items: list, indent: int, parent_key: str | None) -> str:
    pad = "  " * indent
    lines = []
    for item in items:
        if isinstance(item, dict):
            text = emit_event(item, indent + 1, parent_key)
            child_pad = "  " * (indent + 1)
            first, _sep, rest = text.partition("\n")
            lines.append(f"{pad}- {first[len(child_pad) :]}" + (f"\n{rest}" if rest else ""))
        else:
            lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(lines)


def render_event(data: dict) -> str:
    return f"---\n{emit_event(data)}\n---\n"


SLUG_MAXLEN = 30


def slugify_summary(summary: str) -> str:
    """Deterministic directory slug of a summary: camelCase and acronym runs
    split at case boundaries, non-alphanumeric runs collapsed to `-`,
    lowercased, the leading article stripped, cut at the word boundary under
    SLUG_MAXLEN; a summary with no alphanumeric content falls back to
    "lineage". The caller appends `-{ULID}` — the function never handles
    collisions.
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", summary)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", s)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).lower().strip("-")
    s = re.sub(r"^(a|an|the)-", "", s)
    if len(s) > SLUG_MAXLEN:
        cut = s[:SLUG_MAXLEN]
        s = cut[: cut.rfind("-")] if "-" in cut else cut
    return s.strip("-") or "lineage"


def _lineage_home(base_dir: Path, lineage: str) -> Path | None:
    """The single home of a lineage in the base tree, or None.

    Candidates are directories named `<lineage>` or ending in
    `-<lineage>`; a directory holding the founder file wins, ties and
    founderless splits fall back to the sorted-first match.
    """
    candidates = [
        path
        for path in base_dir.rglob("*")
        if ".git" not in path.parts
        and path.is_dir()
        and (path.name == lineage or path.name.endswith(f"-{lineage}"))
    ]
    if not candidates:
        return None
    founder = [path for path in candidates if (path / f"{lineage}.claim.md").is_file()]
    return min(founder or candidates)


def event_relpath(data: dict, base_dir: Path) -> str:
    """`<YYYY-MM>/<slug>-<lineage>/<id>.<kind>.md` under the base (FORMAT.md §1).

    An event on an existing lineage joins the lineage's single existing
    directory verbatim (found by lineage-ULID suffix, whatever its slug or
    month bucket); only a founder creates a directory, in the current month,
    named `<slug>-<lineage>` (bare `<lineage>` when the summary yields no
    slug, and for extensions whose lineage has no home in the tree).
    """
    lineage = data["lineage"]
    home = _lineage_home(base_dir, lineage)
    if home is not None:
        prefix = home.relative_to(base_dir).as_posix()
        return f"{prefix}/{data['id']}.{data['kind']}.md"
    month = datetime.now(UTC).strftime("%Y-%m")
    slug = slugify_summary(data["summary"]) if data["id"] == lineage else ""
    directory = f"{slug}-{lineage}" if slug else lineage
    return f"{month}/{directory}/{data['id']}.{data['kind']}.md"


def precheck(base_dir: Path) -> None:
    """Refuse writing onto a base that already fails `check` (FORMAT.md §6)."""
    result = check_base(base_dir)
    if result.errors:
        raise WriteError(*result.errors)


# Credential-shaped content guard (HIGH CONFIDENCE only — a claim legitimately
# discussing passwords must pass). Deterministic regexes, no dependency.
_PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_TOKEN_PREFIX_RES = (
    ("ghp_", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("github_pat_", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("xox", re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}\b")),
)
# Assignment to a secret name followed by a long value mixing at least three
# character classes (lower/upper/digit/punct) — a bare 20-char lowercase word
# or a code reference does not qualify.
_ASSIGNED_SECRET_RE = re.compile(
    r"\b(password|passwd|secret|token|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?([^\s'\"]{20,})",
    re.IGNORECASE,
)
_SECRET_FIELD_NAMES = (
    "summary",
    "statement",
    "reason",
    "name",
    "unanchored_reason",
)


def _high_entropy(value: str) -> bool:
    classes = sum(
        (
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(not c.isalnum() for c in value),
        )
    )
    return len(value) >= 20 and classes >= 3


def _secret_scan_texts(data: dict) -> list[tuple[str, str]]:
    """(field, text) pairs the guard scans: summary, statement, reason, name,
    unanchored_reason, evidence, every claim question/keyword item (free text —
    same protection), and the structural `proof_query.args`/`proof_query.expect`
    values (stringified — an args mapping may embed a credential)."""
    texts = [(name, data[name]) for name in _SECRET_FIELD_NAMES if isinstance(data.get(name), str)]
    evidence = data.get("evidence")
    if isinstance(evidence, list):
        texts.extend(("evidence", item) for item in evidence if isinstance(item, str))
    questions = data.get("questions")
    if isinstance(questions, list):
        texts.extend(("questions", item) for item in questions if isinstance(item, str))
    keywords = data.get("keywords")
    if isinstance(keywords, list):
        texts.extend(("keywords", item) for item in keywords if isinstance(item, str))
    proof_query = data.get("proof_query")
    if isinstance(proof_query, dict):
        for key in ("args", "expect"):
            value = proof_query.get(key)
            if value is None or isinstance(value, str):
                if isinstance(value, str) and value:
                    texts.append((f"proof_query.{key}", value))
            else:
                texts.append((f"proof_query.{key}", json.dumps(value, ensure_ascii=False)))
    return texts


def scan_for_secrets(data: dict) -> str | None:
    """Return a refusal message when high-confidence credential shapes appear.

    Families: PEM private-key blocks, AWS access key ids, known token prefixes
    (`ghp_`, `github_pat_`, `sk-`, `xoxb/bp/app`), and assignment to a secret
    name followed by a 20+ char mixed-class value. Discussing passwords —
    naming fields, short or single-class values — passes.
    """
    for field, text in _secret_scan_texts(data):
        if _PEM_PRIVATE_KEY_RE.search(text):
            return f"PEM private key block in {field!r}"
        if _AWS_ACCESS_KEY_RE.search(text):
            return f"AWS access key id in {field!r}"
        for prefix, pattern in _TOKEN_PREFIX_RES:
            if pattern.search(text):
                return f"token with known prefix {prefix!r} in {field!r}"
        for match in _ASSIGNED_SECRET_RE.finditer(text):
            if _high_entropy(match.group(2)):
                return (
                    f"assigned high-entropy value to a secret name in {field!r}"
                    f" ({match.group(1).lower()}=…)"
                )
    return None


def _scan_secrets(data: dict, path: str) -> None:
    """Raise as a CheckFailure so the write path refuses before touching disk."""
    message = scan_for_secrets(data)
    if message is not None:
        raise CheckFailure(
            Diag(
                "error",
                E_WRITE_SECRET,
                f"credential-shaped content refused: {message} (nothing is written,"
                " FORMAT.md §6 — store secrets in a secret manager, not a Masora base)",
                path,
            )
        )


def write_and_check(
    base_dir: Path, data: dict, shared: CheckResult | None = None
) -> tuple[str, list[Diag]]:
    """Pre-check, pre-validate, secret-scan, write, re-validate; unlink on post-check failure.

    `shared` (a `checked()` result the caller already computed for this
    operation) replaces the pre-check's own full pass (M3: one shared
    full-base parse per write). The post-check validates the touched
    lineage + the global invariants one new event file can break
    (`_post_check`) — the guarantee is unchanged: a write that leaves the
    base invalid raises and unlinks, so a returned write implies a valid
    base; the full-check semantics stay pinned by `check_base`'s own tests.

    Returns the base-relative path and the checker warnings (they ride along).
    """
    if shared is not None:
        pre = shared if not shared.errors else None
        if pre is None:
            raise WriteError(*shared.errors)
    else:
        pre = check_base(base_dir)
        if pre.errors:
            raise WriteError(*pre.errors)
    rel = event_relpath(data, base_dir)
    try:
        validate_event(data, data["kind"], rel)
        _scan_secrets(data, rel)
    except CheckFailure as exc:
        raise WriteError(exc.diag) from exc
    path = base_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write (temp file + os.replace in the same directory): a
    # concurrent session's `check` never sees a half-written event file, and a
    # failing post-check never leaves a torn file behind that another
    # session's unlink path could mistake for its own valid event.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(render_event(data))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    extra = _post_check(base_dir, data, rel, pre)  # raises WriteError (unlink first)
    return rel, _post_warnings(data, pre, extra)


def _post_warnings(data: dict, pre: CheckResult, extra: list[Diag]) -> list[Diag]:
    """The warnings a full post-write check would report: the pre-check's
    (unchanged by one appended event) plus the new record's own reference
    warnings (W_DANGLING/W_SKEW) and the W_REPLAY arithmetic when the new
    event is a structural claim."""
    warnings = list(pre.warnings) + extra
    if data.get("kind") == "claim" and data.get("class") == "structural":
        count = pre.structural_count + 1
        warnings.append(
            Diag(
                "warning",
                W_REPLAY,
                f"proof replay not wired in standalone check: {count} structural claim(s)"
                " not replayed, outcome unknown",
            )
        )
    return warnings


def _post_check(base_dir: Path, data: dict, rel: str, pre: CheckResult) -> list[Diag]:
    """Incremental post-write validation (M3): the written file re-parsed from
    disk, plus the global invariants ONE new event file can break —
    duplicate ids, tombstone conflicts and the new record's references
    (checked against the single target file each). A valid base plus one
    valid, well-referenced event cannot break any other invariant (a new
    event's reference edges point at existing events — no new cycle; the
    fold's per-lineage state is recomputed from the whole tree on the next
    full check and every consumer of the envelope treats the write path's
    return as "written", never as a fold). Any failure unlinks the
    just-written file first — nothing invalid is ever left behind. Returns
    the new record's own warnings (they ride along)."""
    diags: list[Diag] = []
    path = base_dir / rel
    record = _parse_event_file(path, rel, diags)
    if record is None:
        path.unlink(missing_ok=True)
        raise WriteError(*diags)
    if record.id in pre.event_ids and pre.event_ids[record.id] != rel:
        path.unlink(missing_ok=True)
        raise WriteError(
            Diag(
                "error",
                E_DUP_ID,
                f"event id {record.id} already defined by {pre.event_ids[record.id]}",
                rel,
            )
        )
    if (
        record.id in pre.tombstoned_lineages
        or record.lineage in pre.tombstoned_lineages
        or record.id in pre.tombstoned_events
    ):
        path.unlink(missing_ok=True)
        raise WriteError(
            Diag(
                "error",
                E_TOMBSTONED,
                f"event id or lineage appears in deleted.toml: {record.id} — the lineage was"
                " collected by `masora gc` and its ULIDs can never return (FORMAT.md §7.10);"
                " record the correction as a NEW lineage (a fresh claim with a new ULID),"
                " never as an extension of the collected lineage",
                record.path,
            )
        )
    errors, warnings = _new_record_reference_checks(record, base_dir, pre)
    if errors:
        path.unlink(missing_ok=True)
        raise WriteError(*errors)
    return warnings


def _new_record_reference_checks(
    record: EventRecord, base_dir: Path, pre: CheckResult
) -> tuple[list[Diag], list[Diag]]:
    """Reference checks for the ONE new record (targets/contradicts), against
    the target files themselves. Dangling targets and clock skew keep the
    checker's warning severity — they ride along, they never refuse."""
    errors: list[Diag] = []
    warnings: list[Diag] = []
    for attr in ("targets", "contradicts"):
        target_id = getattr(record, attr)
        if target_id is None:
            continue
        target_rel = pre.event_ids.get(target_id)
        if target_rel is None:
            warnings.append(
                Diag(
                    "warning",
                    W_DANGLING,
                    f"{attr} ULID {target_id} does not resolve to a valid event",
                    record.path,
                )
            )
            continue
        target = _parse_event_file(base_dir / target_rel, target_rel, [])
        if target is None:
            # The target file was fine at pre-check but no longer parses
            # (concurrent modification): the full check would error too.
            errors.append(
                Diag(
                    "error",
                    E_TARGET_KIND,
                    f"{attr} target {target_id} no longer parses",
                    record.path,
                )
            )
            continue
        if attr == "targets":
            allowed = ALLOWED_TARGET_KINDS.get(record.kind)
            if allowed is not None and target.kind not in allowed:
                errors.append(
                    Diag(
                        "error",
                        E_TARGET_KIND,
                        f"{record.kind} must target {sorted(allowed)}, got {target.kind}",
                        record.path,
                    )
                )
            if target.lineage != record.lineage:
                errors.append(
                    Diag(
                        "error",
                        E_LINEAGE,
                        f"lineage mismatch: targets {target.id} in lineage {target.lineage},"
                        f" event in lineage {record.lineage}",
                        record.path,
                    )
                )
            if (
                record.kind == "verify"
                and target.kind == "claim"
                and set(record.snapshot_keys) != set(target.anchor_identities)
            ):
                errors.append(
                    Diag(
                        "error",
                        E_ANCHOR,
                        f"snapshots keys must equal the target's anchor-identity set:"
                        f" expected {sorted(target.anchor_identities)},"
                        f" got {sorted(record.snapshot_keys)}",
                        record.path,
                    )
                )
            if target_id > record.id:
                warnings.append(
                    Diag(
                        "warning",
                        W_SKEW,
                        f"targets ULID {target_id} is lexically greater than event id"
                        f" {record.id} (clock skew tolerated)",
                        record.path,
                    )
                )
        else:
            if target.kind != "claim":
                errors.append(
                    Diag(
                        "error",
                        E_TARGET_KIND,
                        f"contradicts must resolve to a claim version, got {target.kind}",
                        record.path,
                    )
                )
            if target.lineage != record.lineage:
                errors.append(
                    Diag(
                        "error",
                        E_LINEAGE,
                        f"contradicts must resolve to a claim version in the same lineage"
                        f" {record.lineage}, got {target.lineage}",
                        record.path,
                    )
                )
    return errors, warnings
