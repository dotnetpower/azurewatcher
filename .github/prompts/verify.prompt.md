---
mode: agent
description: Run the FDAI pre-commit gates and report a green/red summary.
---

# /verify - run the FDAI pre-commit gates

Run `scripts/verify.sh` from the repo root and report the gate summary.

## Steps

1. Confirm the current working directory is the repo root
   (`git rev-parse --show-toplevel`). If not, cd there.
2. If a Python venv exists at `.venv/`, activate it so `ruff` and `pytest`
   are on PATH: `source .venv/bin/activate`.
3. Run the fast gates first:
   `bash scripts/verify.sh --fast`
4. If the user supplied a pytest path, run focused verification:
   `bash scripts/verify.sh --full ${ARGS}`.
5. If the user explicitly asked for the whole repository, run
   `bash scripts/verify.sh --all`. A generic request such as "with tests"
   means diff-scoped tests, not the whole suite. Use bare `make test-changed`
   only when the worktree contains the current batch alone. If unrelated
   dirty files from parallel sessions are present, use the current session's
   exact committed range:
   `make test-changed DIFF=<commit>^..<commit>`.
   Do not repeat a green run while the commit and relevant environment are
   unchanged.
6. Print the summary block from `verify.sh`. If any gate failed:
   - Name the failing gate.
   - Point at the individual `scripts/check-*.sh` or the offending pytest
     path so the caller can rerun in isolation.
7. Do NOT commit anything from this prompt. Verification only.

## Guardrails

- Never bypass a gate (no `--no-verify`, no gate skipping).
- Never edit the gate scripts to make them pass; treat a failure as a real
  finding.
- Do not touch untracked or WIP files while verifying.
- Do not validate one session by selecting unrelated files from a shared dirty
   worktree. Prefer a separate Git worktree for concurrent sessions.
