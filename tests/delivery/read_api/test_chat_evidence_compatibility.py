from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import pytest

from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    _with_operational_evidence,
)

CONTEXT = {
    "kind": "incident",
    "incident_id": "INC-1",
    "correlation_id": "corr-1",
}


class _LegacyResolver:
    async def resolve(self, prompt: str) -> dict[str, Any]:
        return {"status": "matched", "prompt": prompt}


class _ContextResolver:
    def __init__(self) -> None:
        self.context: dict[str, str] | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        conversation_context: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self.context = dict(conversation_context) if conversation_context is not None else None
        return {"status": "matched", "prompt": prompt}


class _KeywordResolver:
    def __init__(self) -> None:
        self.keywords: dict[str, object] = {}

    async def resolve(self, prompt: str, **kwargs: object) -> dict[str, Any]:
        self.keywords = kwargs
        return {"status": "matched", "prompt": prompt}


async def test_legacy_resolver_remains_compatible_with_bound_conversation() -> None:
    enriched = await _with_operational_evidence(
        "continue",
        {},
        _LegacyResolver(),  # type: ignore[arg-type]
        conversation_context=CONTEXT,
    )

    assert enriched["_operational_evidence"]["status"] == "matched"


async def test_context_aware_resolver_receives_exact_binding() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "continue",
        {},
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.context == CONTEXT


async def test_trace_screen_correlation_becomes_exact_selection_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "what caused the error?",
        {
            "routeId": "trace",
            "facts": [
                {"key": "load_status", "value": "error"},
                {"key": "correlation_id", "value": "corr-screen"},
            ],
        },
        resolver,
    )

    assert resolver.context == {
        "kind": "incident",
        "incident_id": "INC-corr-screen",
        "correlation_id": "corr-screen",
    }


async def test_explicit_binding_wins_over_trace_screen_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "continue",
        {
            "routeId": "trace",
            "facts": [{"key": "correlation_id", "value": "corr-screen"}],
        },
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.context == CONTEXT


async def test_variadic_keyword_resolver_receives_binding() -> None:
    resolver = _KeywordResolver()

    await _with_operational_evidence(
        "continue",
        {},
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.keywords == {"conversation_context": CONTEXT}


async def test_resolver_internal_type_error_is_not_misclassified_as_legacy() -> None:
    class _FailingResolver(_ContextResolver):
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ) -> dict[str, Any]:
            raise TypeError("resolver defect")

    with pytest.raises(TypeError, match="resolver defect"):
        await _with_operational_evidence(
            "continue",
            {},
            _FailingResolver(),
            conversation_context=CONTEXT,
        )


async def test_uninspectable_resolver_uses_current_context_contract() -> None:
    resolver = _ContextResolver()

    with patch(
        "fdai.delivery.read_api.routes.chat_evidence_enrichment.signature",
        side_effect=ValueError("signature unavailable"),
    ):
        await _with_operational_evidence(
            "continue",
            {},
            resolver,
            conversation_context=CONTEXT,
        )

    assert resolver.context == CONTEXT
