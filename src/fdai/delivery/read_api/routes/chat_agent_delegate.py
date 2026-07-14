"""Read-only adapter from Command Deck chat to the pantheon runtime."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fdai.agents import PantheonRuntime


@dataclass(frozen=True, slots=True)
class PantheonChatDelegate:
    """Route a web question through Bragi without conversational side effects."""

    runtime: PantheonRuntime

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        turn = await self.runtime.ask(
            session_id=_scoped_session_id(user_id, session_id),
            user_id=user_id,
            question=prompt,
            allow_action_proposal=False,
            materialize_handoff=False,
        )
        if turn is None or not isinstance(turn.answer, dict):
            return None
        answer = turn.answer.get("answer")
        primary = turn.answer.get("primary_agent")
        if not isinstance(answer, str) or not answer or not isinstance(primary, str):
            return None
        facts = turn.answer.get("facts")
        contributors = turn.answer.get("contributors")
        contributor_answers = turn.answer.get("contributor_answers")
        return {
            "primary_agent": primary,
            "answer": answer,
            "facts": dict(facts) if isinstance(facts, dict) else {},
            "contributors": (
                [item for item in contributors[:8] if isinstance(item, str)]
                if isinstance(contributors, list)
                else []
            ),
            "contributor_answers": (
                [dict(item) for item in contributor_answers[:8] if isinstance(item, dict)]
                if isinstance(contributor_answers, list)
                else []
            ),
            "trace_ref": str(turn.answer.get("trace_ref") or "")[:256],
        }


def _scoped_session_id(user_id: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{user_id}\0{session_id}".encode()).hexdigest()[:32]
    return f"web-{digest}"


__all__ = ["PantheonChatDelegate"]
