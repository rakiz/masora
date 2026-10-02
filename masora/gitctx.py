"""Git relation adapter (MASORA_DESIGN.md §6.2): the per-version git context
B(v) computed against the asking checkout at index build time.

The adapter answers ONE question per claim version — where does its
establishing commit (the `recorded_at.commit` of the claim event) sit against
the asking HEAD — and labels it:

- `in_line` — the commit is an ancestor-or-equal of HEAD (a freshly written
  fact is in its own line; HEAD-equal counts);
- `ahead` — the commit is a PROPER descendant of HEAD AND an
  ancestor-or-equal of the asking branch's upstream ref AS PRESENT LOCALLY
  (`git rev-parse --verify <branch>@{upstream}` — never fetched; detached
  HEAD, a missing branch or a missing upstream means no `ahead` is provable,
  §12.16(n));
- `out_of_line` — provably NOT `in_line` and NOT `ahead` (the probe answers
  prove the commit is off the ancestor-or-equal position and cannot reach the
  ahead position);
- `relation_unknown` — probes ran and proved the commit off the
  ancestor-or-equal position, but a needed probe of the ahead test failed
  (git error / missing object): the proven partial result is never demoted,
  the relation label stays undecided;
- `None` (`unprovable`) — no establishing commit, the repo is a shallow
  clone, the asking HEAD does not resolve, or the probe budget blocked or
  failed the primary probe: nothing was proven at all.

Probes are `git merge-base --is-ancestor a b` (exit 0 = yes, 1 = proven no,
any other exit = probe failure — never read as a no). They are memoized per
ORDERED sha pair and share ONE budget per index build; lineages are processed
in ascending lineage-id (ULID) order and versions in ascending ULID order so
the budget is deterministic — adding an unrelated lineage never changes an
earlier lineage's result within the budget. There is NO implicit fetch and no
network: the adapter reads the local object store only.

The counterfactual `degraded` test (§6.2) is the under-flagging-averse
decision procedure over the unprovable contexts: a lineage's
`context_ordering` is `degraded` iff some version's context is unprovable
(`relation_unknown` does NOT count — its not-in_line knowledge is proven) AND
hypothetically promoting that version to each candidate tier-1 position it
could take (`in_line`, `ahead`) or demoting it to tier 2 (`out_of_line`)
would change the fold's observable result (displayed, shadow, restored).
"""

from __future__ import annotations

import enum
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .fold import TIER1_RELATIONS, Event, VersionContext, fold_lineage
from .sync import git_env

# One shared probe budget per index build (MASORA_DESIGN.md §6.2): the cap on
# `git merge-base --is-ancestor` spawns. Sized to fully resolve a base of
# ~300 versions (<= 3 probes per version plus the tier-1 ancestry pairs) with
# headroom; a larger base degrades VISIBLY (unprovable contexts + the
# degraded counterfactual) instead of stalling the build.
PROBE_BUDGET = 1024


class Answer(enum.Enum):
    """The outcome of one ancestry probe. A non-0/1 git exit is FAILED —
    never a no; BLOCKED means the shared build budget is exhausted."""

    YES = "yes"
    NO = "no"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AskingLine:
    """The asking checkout's line, resolved locally (never fetched).

    `head` is the asking HEAD (None: not a checkout or empty repo); `upstream`
    is the commit of the current branch's upstream ref as present locally
    (None: detached HEAD, missing branch configuration or missing upstream —
    no `ahead` is provable, §12.16(n)); `shallow` marks a shallow clone, whose
    negative ancestry answers are untrustworthy.
    """

    head: str | None
    branch: str | None
    upstream: str | None
    shallow: bool


def asking_line(repo: Path) -> AskingLine:
    """Resolve the asking line of `repo` — three local git reads, no fetch."""
    head = _git_text(repo, "rev-parse", "HEAD")
    branch = _git_text(repo, "symbolic-ref", "--short", "HEAD")
    upstream = None
    if head is not None and branch is not None:
        upstream = _git_text(repo, "rev-parse", "--verify", f"{branch}@{{upstream}}")
    shallow = _git_text(repo, "rev-parse", "--is-shallow-repository") == "true"
    return AskingLine(head=head, branch=branch, upstream=upstream, shallow=shallow)


def _git_text(repo: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


class RelationProber:
    """Memoized, budgeted ancestry probes shared by ONE index build.

    The memo is keyed by the ORDERED sha pair (a, b) — `is_ancestor(a, b)` —
    so a repeated question (across versions, lineages, or the two directions
    of one pair) spawns git once. The budget caps the git spawns per build;
    when it is exhausted every further probe answers BLOCKED without spawning.
    """

    def __init__(self, repo: Path, line: AskingLine, budget: int | None = None):
        self.repo = repo
        self.line = line
        # Resolved at call time (not a default argument) so a test can
        # monkeypatch the module constant and shrink a whole build's budget.
        self.budget = PROBE_BUDGET if budget is None else budget
        self.used = 0
        self._memo: dict[tuple[str, str], Answer] = {}

    @property
    def probe_count(self) -> int:
        """Git spawns so far (memo hits are free) — the memoization evidence."""
        return self.used

    def is_ancestor(self, a: str, b: str) -> Answer:
        """YES when a is an ancestor-or-equal of b, NO when proven not, FAILED
        on a git error (missing object included), BLOCKED past the budget."""
        key = (a, b)
        if key in self._memo:
            return self._memo[key]
        if self.used >= self.budget:
            return Answer.BLOCKED
        self.used += 1
        proc = subprocess.run(
            ["git", "-C", str(self.repo), "merge-base", "--is-ancestor", a, b],
            capture_output=True,
            text=True,
            check=False,
            env=git_env(),
        )
        answer = {0: Answer.YES, 1: Answer.NO}.get(proc.returncode, Answer.FAILED)
        self._memo[key] = answer
        return answer

    def lineage_contexts(self, establishing: Mapping[str, str | None]) -> dict[str, VersionContext]:
        """The per-version context of ONE lineage: relations first (versions in
        ascending ULID order — the deterministic budget order), then the
        ancestry-maxima input among the tier-1 candidates (a failed or blocked
        pairwise probe reads as INCOMPARABLE — it never demotes a proven
        relation). A version whose establishing commit is None is unprovable.
        """
        contexts: dict[str, VersionContext] = {}
        tier1: list[tuple[str, str]] = []
        for version in sorted(establishing):
            relation = self._relation(establishing[version])
            contexts[version] = VersionContext(version, relation)
            if relation in TIER1_RELATIONS:
                tier1.append((version, establishing[version]))
        ancestors: dict[str, set[str]] = {version: set() for version, _ in tier1}
        for i, (v, cv) in enumerate(tier1):
            for w, cw in tier1[i + 1 :]:
                if cv == cw:
                    # Same establishing commit: neither version PROPERLY
                    # descends from the other — both stay maxima.
                    continue
                if self.is_ancestor(cv, cw) is Answer.YES:
                    ancestors[w].add(v)
                if self.is_ancestor(cw, cv) is Answer.YES:
                    ancestors[v].add(w)
        for version, anc in ancestors.items():
            contexts[version] = VersionContext(version, contexts[version].relation, frozenset(anc))
        return contexts

    def _relation(self, commit: str | None) -> str | None:
        """The §6.2 relation of one establishing commit against the asking line.

        The exact decision table is documented in the module docstring: the
        primary probe (commit vs HEAD) blocked or failed leaves NOTHING
        proven — unprovable; a failed probe AFTER not-in_line was proven keeps
        the proven half and labels the rest `relation_unknown`.
        """
        if not commit:
            return None
        if self.line.head is None:
            return None
        if self.line.shallow:
            # A shallow clone's negative answers may be wrong (the ancestry
            # path can be cut off at the shallow boundary) — nothing is
            # provable, the degraded counterfactual covers the lineage.
            return None
        head = self.line.head
        first = self.is_ancestor(commit, head)
        if first in (Answer.BLOCKED, Answer.FAILED):
            return None
        if first is Answer.YES:
            return "in_line"
        # Proven: the commit is NOT an ancestor-or-equal of HEAD.
        if self.line.upstream is None:
            # Detached HEAD or missing upstream: no ahead is provable —
            # a structural impossibility, not a probe failure.
            return "out_of_line"
        second = self.is_ancestor(head, commit)
        if second is Answer.BLOCKED:
            return None
        if second is Answer.FAILED:
            return "relation_unknown"
        if second is Answer.NO:
            return "out_of_line"
        # Proven: the commit is a PROPER descendant of HEAD (first is NO, so
        # the commits differ).
        third = self.is_ancestor(commit, self.line.upstream)
        if third is Answer.BLOCKED:
            return None
        if third is Answer.FAILED:
            return "relation_unknown"
        return "ahead" if third is Answer.YES else "out_of_line"


def context_ordering(
    lineage: str,
    events: list[Event],
    activity: Mapping[str, bool],
    eligible: list[str],
    outcomes: Mapping[str, str],
    contexts: Mapping[str, VersionContext],
) -> str:
    """The per-lineage `context_ordering`: `exact` | `degraded` (MASORA_DESIGN
    §6.2, counterfactual).

    `degraded` iff some version's context is unprovable (`relation_unknown`
    does NOT count — its not-in_line knowledge is proven, its residual
    ahead-uncertainty is the version label's own honest report) AND a
    hypothetical change of THAT version's relation would change the fold's
    observable result — what displays, the shadow decision (`resolution`
    None) or the `restored` decision. Each hypothetical promotes the version
    to a candidate tier-1 position (`in_line`, `ahead`) or demotes it to tier
    2 (`out_of_line`); the hypothetical context carries no ancestry edges (the
    strongest hypothesis: the version is a tier-1 maximum). `off-version` is
    OUT of scope — its guard requires a PROVABLE relation (§6.2), and the
    tier-2 demotion is observable-neutral in the current fold.
    """

    def observable(ctx: Mapping[str, VersionContext]) -> tuple:
        folded = fold_lineage(lineage, events, activity, eligible, outcomes=outcomes, contexts=ctx)
        return (folded.displayed, folded.restored, folded.resolution)

    was = observable(contexts or {})
    for version in sorted(eligible):
        current = contexts.get(version)
        if current is not None and current.relation is not None:
            continue
        for relation in ("in_line", "ahead", "out_of_line"):
            hypothetical = dict(contexts)
            hypothetical[version] = VersionContext(version, relation)
            if observable(hypothetical) != was:
                return "degraded"
    return "exact"
