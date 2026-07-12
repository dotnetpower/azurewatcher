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
4. If the user asked for a full check (`--full` or "with tests"), run:
   `bash scripts/verify.sh --full ${ARGS}` where `${ARGS}` is an optional
   pytest path. Omit `${ARGS}` to run the whole suite.
5. Print the summary block from `verify.sh`. If any gate failed:
   - Name the failing gate.
   - Point at the individual `scripts/check-*.sh` or the offending pytest
     path so the caller can rerun in isolation.
6. Do NOT commit anything from this prompt. Verification only.

## Guardrails

- Never bypass a gate (no `--no-verify`, no gate skipping).
- Never edit the gate scripts to make them pass; treat a failure as a real
  finding.
- Do not touch untracked or WIP files while verifying.
