# INPROGRESS

<!-- Current state of the running phase. Updated as work happens — tick
     [x]/[ ] and record blockers as soon as they appear, not only before
     commit. Resume here after any session interruption.
     Phase done -> entry in CHANGELOG.md, then reset this file with the next
     phase's detail (never empty, never stale). -->

## Current phase

Phase 1: v0 core (TODO.md). Open questions settled 2026-09-25 — decisions in
MASORA_DESIGN.md §12, SPEC.md amended. Final audit (strong-review) applied:
its 8 document blockers and 11 inconsistencies are fixed; remaining
clarifications are listed in TODO.md ("settle as each task starts").
Implementation not started.

## Steps

- [ ] Pre-flight: check name availability — `pip index versions masora`, GitHub, npm (§3).
- [ ] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + frontmatter schema (settled, §12.5) + layout of §7.
- [ ] `masora check`: validates event schema and append-only history (local command; run by `sync`).

(Remainder of the phase: see TODO.md.)

## Blockers

None.
