# Refoundation runbook — accepting a remote history rewrite

The Masora base is an append-only git ledger; `masora sync` treats any
rewrite of a known event id (a modified or deleted file that `origin/main`
still knows) as tampering and refuses it with `E-REWRITE`. That refusal is
deliberate and stays: the tool never guesses whether a rewritten remote is a
legitimate refoundation or an attack.

This runbook is the explicit, human path for the legitimate case.

## When to refound

- A force-push refoundation of the base's `main` (history reorganized,
  squashed, or rebased out-of-band).
- Secret removal from history: the base's git history leaked a credential
  and was rewritten (e.g. with `git filter-repo` / BFG) to drop it.

If you cannot verify out-of-band WHY the remote changed, stop: treat it as a
tampering incident, not a refoundation.

## The never-automatic invariant

`masora reset --from-origin` is the only acceptance move, it is NEVER run
automatically, and nothing in `masora sync`, `masora index`, the MCP server
or any hook may call it. The command is deliberately NEUTRAL: it does not
judge whether the remote rewrite was a refoundation or an attack — it
requires explicit `--yes` confirmation and prints exactly what is discarded,
so tamper evidence stays intact (AUDIT.md, operational risk 3).

## Steps

1. **Verify out-of-band** that the rewrite was intended (who pushed it, why,
   from where). This step is yours; the tool cannot do it for you.
2. **Archive the old clone** — the discarded local history is the evidence:
   ```sh
   mv ~/.local/share/masora/bases/<name> ~/.local/share/masora/bases/<name>-pre-reset
   masora setup --base <url>          # fresh clone (skips to step 5), OR keep reading
   ```
   Keeping the same clone instead: make sure the working tree is clean.
3. **Plan the reset** (nothing is written, exit 3):
   ```sh
   masora reset <base-dir> --from-origin
   ```
   A dirty working tree is refused (`E-RESET-DIRTY`) — commit or discard
   first. The plan lists every local-only commit (`origin/main..main`) the
   `--yes` run will discard. Read it.
4. **Execute**:
   ```sh
   masora reset <base-dir> --from-origin --yes
   ```
5. **Rebuild the indexes**:
   ```sh
   masora index <base-dir> --repo <code-checkout>
   ```
6. **Re-validate**: `masora check <base-dir>` must come back clean. If the
   reset tree still reports `E-REWRITE`, the local history disagrees with
   origin beyond a plain reset — compare against the archived clone and
   investigate before touching anything else.
