# AGENTS.md

This repository uses the Copilot instruction hub at
[.github/copilot-instructions.md](.github/copilot-instructions.md) as the
canonical entry point for AI coding agents.

Every rule that governs code, documentation, safety, language, and the agent
pantheon lives under `.github/instructions/*.instructions.md` (auto-loaded by
scope) and the long-form guides under `.github/skills/**/SKILL.md`.

Start there. This file exists so tools that read a root-level `AGENTS.md`
(Cursor, Aider, Claude Code, etc.) discover the same contract that Copilot
follows in this repo.

## Quick pointers

- **Contract hub**: [.github/copilot-instructions.md](.github/copilot-instructions.md)
- **Coding rules**: [.github/instructions/coding-conventions.instructions.md](.github/instructions/coding-conventions.instructions.md)
- **Architecture**: [.github/instructions/architecture.instructions.md](.github/instructions/architecture.instructions.md)
- **Language policy (L0-L3)**: [.github/instructions/language.instructions.md](.github/instructions/language.instructions.md)
- **Agent pantheon**: [.github/instructions/agent-pantheon.instructions.md](.github/instructions/agent-pantheon.instructions.md)
- **Docs style**: [.github/instructions/documentation-style.instructions.md](.github/instructions/documentation-style.instructions.md)
- **Fork guide**: [docs/roadmap/fork-and-sequencing/downstream-fork-guide.md](docs/roadmap/fork-and-sequencing/downstream-fork-guide.md)

## Pre-commit gate (single entry)

Run `scripts/verify.sh` before committing (Ruff + strict mypy + fast text gates).
Add `--full` to include the pytest suite.
