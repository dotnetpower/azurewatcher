---
mode: agent
description: Resume where the previous session stopped - summarize recent sessions and surface unfinished work.
---

# /resume-session - resume the previous session

Use the chronicle skill and local session store to find what the
maintainer was working on most recently and give a short, actionable
summary so the next batch can start immediately.

## Steps

1. **Query recent sessions** with the session-store SQL:
   ```sql
   SELECT session_id, started_at, ended_at, summary
   FROM sessions
   WHERE ended_at > datetime('now', '-3 days')
   ORDER BY ended_at DESC
   LIMIT 5;
   ```
2. **Pull recent commits** on the current branch:
   `git --no-pager log --oneline -15`
3. **Show working-tree state** (respect maintainer WIP):
   `git status --short`
   `git rev-list @{u}..HEAD --oneline`
4. **Check for in-progress todos** (`manage_todo_list`) and repo-memory
   backlog markers under `/memories/repo/`.
5. Produce a concise summary in this shape:
   - **Last commit topic**: <one line>
   - **Working tree**: N modified, M new. Names of top 5 files.
   - **Unpushed commits**: N. Topics.
   - **Open todos**: any in-progress from the todo list.
   - **Suggested next batch**: one concrete next step tied to the
     coding-ability or chat-improvement playbook, if applicable.

## Guardrails

- **Read-only.** Do not commit, do not stash, do not touch the working
  tree. This prompt just surfaces state.
- Do not push. Push is always a maintainer decision.
- If the working tree has WIP, remind the caller that autonomous
  batches must use per-file `git add`, never `git add -A`.
- customer-agnostic in the summary (no real sub / tenant / customer
  names, even if they appear in session titles or commit messages -
  redact them in the output).
