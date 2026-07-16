"""Command Deck route registration for the read API composition root."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.read_api.read_model import ConsoleReadModel
from fdai.delivery.read_api.routes.chat import (
    DEFAULT_ROUTE_PATH,
    AgentChatDelegate,
    ChatBackend,
    ChatWebSearchEvidenceResolver,
    LatencyRoutedChatBackend,
    describe_backend,
    make_chat_health_route,
    make_chat_route,
    make_chat_stream_route,
)
from fdai.delivery.read_api.routes.chat_evidence import OperationalEvidenceResolver
from fdai.delivery.read_api.routes.chat_semantic import semantic_verifier_from_env
from fdai.delivery.read_api.routes.chat_tools import ReadModelChatTools
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore


def append_chat_routes(
    routes: list[BaseRoute],
    *,
    backend: ChatBackend | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_settings: object | None = None,
    authorize: Callable[[Request], Awaitable[str]],
    read_model: ConsoleReadModel,
    core_paths: Collection[str],
    panel_paths: Collection[str],
    logger: logging.Logger,
) -> None:
    """Append the optional chat, stream, and health routes."""

    if backend is None:
        return
    if DEFAULT_ROUTE_PATH in core_paths:
        raise ValueError(f"chat path {DEFAULT_ROUTE_PATH!r} collides with a core route")
    if DEFAULT_ROUTE_PATH in panel_paths:
        raise ValueError(f"chat path {DEFAULT_ROUTE_PATH!r} collides with a panel path")

    evidence = OperationalEvidenceResolver(read_model)
    tools = ReadModelChatTools(read_model)
    semantic_verifier = semantic_verifier_from_env()
    routes.extend(
        (
            make_chat_route(
                backend=backend,
                authorize=authorize,
                evidence_resolver=evidence,
                tool_resolver=tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                semantic_verifier=semantic_verifier,
                conversation_policy_store=conversation_policy_store,
                conversation_history_store=conversation_history_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=authorize,
                evidence_resolver=evidence,
                tool_resolver=tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                semantic_verifier=semantic_verifier,
                conversation_policy_store=conversation_policy_store,
                conversation_history_store=conversation_history_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
            ),
            make_chat_health_route(
                backend=backend,
                authorize=authorize,
                web_search_resolver=web_search_resolver,
            ),
        )
    )

    descriptor = describe_backend(backend)
    if descriptor.get("available"):
        logger.warning(
            "CommandDeck chat backend ready: mode=%s model=%s endpoint=%s",
            descriptor.get("mode"),
            descriptor.get("model"),
            descriptor.get("endpoint"),
        )
    else:
        logger.warning(
            "CommandDeck chat backend NOT wired - the FE will fall back to the "
            "deterministic answerer. Set FDAI_NARRATOR_* env vars or ship "
            "resolved-models.json to enable the LLM path."
        )


def is_routed_chat_backend(backend: object) -> bool:
    """Return whether the optional chat backend uses latency routing."""
    return isinstance(backend, LatencyRoutedChatBackend)


__all__ = ["append_chat_routes", "is_routed_chat_backend"]
