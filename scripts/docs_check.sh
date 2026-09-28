#!/usr/bin/env bash
# Pre-commit docs-freshness check.
#
# Asks the opencode agent whether the staged documentation is still coherent
# with the staged code, then passes or fails the commit. Fail-open by design:
# a missing CLI, an agent timeout or an unparseable verdict skips the check
# instead of blocking a commit.
#
# Usage:
#   scripts/docs_check.sh          # inspect staged files (pre-commit)
#   scripts/docs_check.sh --all    # inspect every tracked file
set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "docs_fresh: not inside a git repository — check SKIPPED (fail-open)"
    exit 0
}
cd "$REPO_ROOT" || exit 0

# --- Collect the files under review ------------------------------------------
if [ "${1:-}" = "--all" ]; then
    files="$(git ls-files)"
else
    files="$(git diff --cached --name-only)"
fi

# Relevant = any *.md, or anything under masora/ or tests/ (code changes can
# stale the docs just as well as doc changes).
relevant=""
while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
        *.md|masora/*|tests/*) relevant="${relevant}${f}"$'\n' ;;
    esac
done <<EOF
$files
EOF

if [ -z "$relevant" ]; then
    echo "docs_fresh: skipped (no md/code staged)"
    exit 0
fi

# --- Require the agent CLI ---------------------------------------------------
if ! command -v opencode >/dev/null 2>&1; then
    echo "docs_fresh: opencode CLI not found — check SKIPPED (fail-open)"
    exit 0
fi

# --- Build the prompt --------------------------------------------------------
prompt="Read the following files from the working tree:

${relevant}
Verify documentation FRESHNESS ONLY. Read-only inspection: do not create, modify, delete or stage any file, and do not run any git command that writes (add, commit, reset, clean, gc, prune, stash, checkout, restore). Report:
- stale status lines (e.g. \"nothing implemented yet\")
- outdated counts, exit codes and command examples
- references to files, or FORMAT.md sections, that do not exist
- workflow-file coherence (a CHANGELOG entry present when a task file
  changed; INPROGRESS not contradicting the staged content)

Reply with EXACTLY one of:
- DOCS-OK
- one or more lines of the form: DOCS-STALE: <file>: <issue>
No other text."

# --- Run the agent with a macOS-portable timeout -----------------------------
out="$(mktemp "${TMPDIR:-/tmp}/docs_fresh.XXXXXX")"
opencode run "$prompt" >"$out" 2>&1 &
pid=$!

timeout=180
elapsed=0
while kill -0 "$pid" 2>/dev/null; do
    if [ "$elapsed" -ge "$timeout" ]; then
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
        echo "docs_fresh: agent timed out — check SKIPPED"
        rm -f "$out"
        exit 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done
wait "$pid" 2>/dev/null

# --- Parse the verdict -------------------------------------------------------
# Stale matches are evaluated first: a response containing both DOCS-STALE: and
# DOCS-OK must never let the OK mask a stale finding.
stale="$(grep -E '^DOCS-STALE: ' "$out")"
if [ -n "$stale" ]; then
    printf '%s\n' "$stale"
    echo "docs_fresh: stale documentation — update the docs before committing"
    rm -f "$out"
    exit 1
fi

if grep -qx 'DOCS-OK' "$out"; then
    echo "docs_fresh: OK"
    rm -f "$out"
    exit 0
fi

echo "docs_fresh: unparseable verdict — check SKIPPED (fail-open)"
echo "----- agent output -----"
while IFS= read -r line; do
    printf '%s\n' "$line"
done <"$out"
echo "------------------------"
rm -f "$out"
exit 0
