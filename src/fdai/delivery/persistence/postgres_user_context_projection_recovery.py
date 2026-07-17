"""Durable replay of user-context ontology upserts from source records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.persistence.postgres_briefing import (
    _RUN_SELECT,
    _SUBSCRIPTION_SELECT,
    _policy,
    _run,
    _subscription,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresUserContextStoreConfig,
    _conversation,
    _memory,
    _preference,
    _turn,
)
from fdai.delivery.persistence.postgres_workflow_definition import (
    _BINDING_SELECT,
    _DEFINITION_SELECT,
    _binding,
    _definition,
)
from fdai.shared.providers.user_context import ConversationTurnRecord


def _turn_exchanges(
    turns: tuple[ConversationTurnRecord, ...],
) -> tuple[tuple[ConversationTurnRecord, ConversationTurnRecord], ...]:
    operators = {
        turn.idempotency_key.removesuffix(":operator"): turn
        for turn in turns
        if turn.idempotency_key.endswith(":operator")
    }
    return tuple(
        (operator, assistant)
        for assistant in turns
        if assistant.idempotency_key.endswith(":assistant")
        and (operator := operators.get(assistant.idempotency_key.removesuffix(":assistant")))
        is not None
    )


@dataclass(frozen=True, slots=True)
class ProjectionUpsertJob:
    projection_kind: str
    principal_id: str
    record_id: str
    attempts: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.projection_kind, self.principal_id, self.record_id)


class PostgresUserContextProjectionRecovery:
    def __init__(
        self,
        *,
        config: PostgresUserContextStoreConfig,
        projector: UserContextOntologyProjector,
    ) -> None:
        self._config = config
        self._projector = projector

    async def claim(
        self,
        *,
        now: datetime,
        limit: int = 500,
        lease_seconds: int = 300,
    ) -> tuple[ProjectionUpsertJob, ...]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit MUST be in [1, 5000]")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds MUST be in [1, 3600]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT projection_kind, principal_id, record_id, attempts "
                "FROM user_context_projection_upsert_queue WHERE available_at <= %s "
                "AND (leased_until IS NULL OR leased_until <= %s) "
                "ORDER BY available_at, projection_kind, principal_id, record_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s",
                (now, now, limit),
            )
            rows = list(await cursor.fetchall())
            if rows:
                lease_until = now + timedelta(seconds=lease_seconds)
                async with connection.cursor() as batch:
                    await batch.executemany(
                        "UPDATE user_context_projection_upsert_queue SET leased_until = %s "
                        "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
                        [
                            (
                                lease_until,
                                str(row["projection_kind"]),
                                str(row["principal_id"]),
                                str(row["record_id"]),
                            )
                            for row in rows
                        ],
                    )
        return tuple(
            ProjectionUpsertJob(
                projection_kind=str(row["projection_kind"]),
                principal_id=str(row["principal_id"]),
                record_id=str(row["record_id"]),
                attempts=int(row["attempts"]),
            )
            for row in rows
        )

    async def project(self, job: ProjectionUpsertJob) -> bool:
        if job.projection_kind == "conversation_bundle":
            return await self._project_conversation_bundle(job)
        if job.projection_kind == "preference":
            record = await self._one(
                "SELECT principal_id, locale, verbosity, answer_detail, answer_format, "
                "answer_preferences_enabled, answer_intent_detail, answer_intent_format, "
                "timezone, share_with_learner, "
                "revision, updated_at FROM user_preference "
                "WHERE principal_id = %s",
                (job.principal_id,),
                _preference,
            )
            if record is not None:
                await self._projector.project_preference(record)
            return record is not None
        if job.projection_kind == "memory":
            record = await self._one(
                "SELECT principal_id, memory_id, category, body, source_turn_id, "
                "consented_at, created_at, expires_at, superseded_by "
                "FROM user_memory_fact WHERE principal_id = %s AND memory_id = %s",
                (job.principal_id, job.record_id),
                _memory,
            )
            if record is not None:
                await self._projector.project_memory(record)
            return record is not None
        if job.projection_kind == "policy":
            record = await self._one(
                "SELECT principal_id, policy_id, kind, enabled, revision, confirmed_at, "
                "source_turn_id, briefing_spec, response_defaults FROM conversation_policy "
                "WHERE principal_id = %s AND policy_id = %s",
                (job.principal_id, job.record_id),
                _policy,
            )
            if record is not None:
                await self._projector.project_policy(record)
            return record is not None
        if job.projection_kind == "briefing_subscription":
            record = await self._one(
                _SUBSCRIPTION_SELECT + " WHERE principal_id = %s AND subscription_id = %s",
                (job.principal_id, job.record_id),
                _subscription,
            )
            if record is not None:
                await self._projector.project_subscription(record)
            return record is not None
        if job.projection_kind == "briefing_run":
            record = await self._one(
                _RUN_SELECT + " WHERE principal_id = %s AND run_id = %s",
                (job.principal_id, job.record_id),
                _run,
            )
            if record is not None:
                await self._projector.project_briefing_run(record)
            return record is not None
        if job.projection_kind == "workflow_definition":
            record = await self._one(
                _DEFINITION_SELECT + " WHERE definition_id = %s",
                (job.record_id,),
                _definition,
            )
            if record is not None:
                await self._projector.project_workflow_definition(record)
            return record is not None
        if job.projection_kind == "workflow_binding":
            record = await self._one(
                _BINDING_SELECT + " WHERE principal_id = %s AND binding_id = %s",
                (job.principal_id, job.record_id),
                _binding,
            )
            if record is not None:
                await self._projector.project_workflow_binding(record)
            return record is not None
        raise ValueError(f"unsupported projection kind {job.projection_kind!r}")

    async def complete(self, job: ProjectionUpsertJob) -> None:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM user_context_projection_upsert_queue "
                "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
                job.key,
            )

    async def retry(
        self,
        job: ProjectionUpsertJob,
        *,
        available_at: datetime,
        error: str,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "UPDATE user_context_projection_upsert_queue SET attempts = attempts + 1, "
                "available_at = %s, leased_until = NULL, last_error = %s "
                "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
                (available_at, error[:500], *job.key),
            )

    async def dead_letter(self, job: ProjectionUpsertJob, *, error: str) -> None:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "UPDATE user_context_projection_upsert_queue SET attempts = attempts + 1, "
                "available_at = 'infinity', leased_until = NULL, last_error = %s "
                "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
                (f"dead-letter:{error}"[:500], *job.key),
            )

    async def _project_conversation_bundle(self, job: ProjectionUpsertJob) -> bool:
        async with await self._connect() as connection:
            await self._timeout(connection)
            conversation_cursor = await connection.execute(
                "SELECT principal_id, conversation_id, channel_id, started_at, "
                "last_active, status FROM conversation_record "
                "WHERE principal_id = %s AND conversation_id = %s",
                (job.principal_id, job.record_id),
            )
            conversation_row = await conversation_cursor.fetchone()
            if conversation_row is None:
                return False
            turns_cursor = await connection.execute(
                "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
                "recorded_at, idempotency_key, metadata FROM conversation_turn "
                "WHERE principal_id = %s AND conversation_id = %s ORDER BY turn_index",
                (job.principal_id, job.record_id),
            )
            turns = tuple(_turn(row) for row in await turns_cursor.fetchall())
        conversation = _conversation(conversation_row)
        await self._projector.project_conversation(conversation)
        for operator, assistant in _turn_exchanges(turns):
            await self._projector.project_turn_exchange(
                conversation=conversation,
                operator=operator,
                assistant=assistant,
            )
        return True

    async def _one(
        self,
        query: str,
        parameters: tuple[object, ...],
        mapper: Any,
    ) -> Any | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
        return mapper(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


__all__ = ["PostgresUserContextProjectionRecovery", "ProjectionUpsertJob"]
