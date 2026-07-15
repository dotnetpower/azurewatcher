"""Optional local semantic verifier configuration and shadow behavior."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from fdai.delivery.read_api.routes.chat_semantic import (
    OnnxSemanticVerifierConfig,
    SemanticVerification,
    semantic_premise,
    semantic_verifier_from_env,
)
from fdai.delivery.read_api.routes.chat_verification import (
    attach_semantic_shadow,
    verify_answer,
)


class _Verifier:
    def __init__(self, result: SemanticVerification) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def verify(self, *, premise: str, hypothesis: str) -> SemanticVerification:
        self.calls.append((premise, hypothesis))
        return self.result


class _SlowVerifier:
    async def verify(self, *, premise: str, hypothesis: str) -> SemanticVerification:
        await asyncio.sleep(1)
        raise AssertionError("timeout should cancel semantic inference")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_env_factory_is_disabled_when_no_settings_exist() -> None:
    assert semantic_verifier_from_env({}) is None


def test_env_factory_requires_complete_artifact_configuration() -> None:
    with pytest.raises(ValueError, match="MUST be complete"):
        semantic_verifier_from_env({"FDAI_SEMANTIC_VERIFIER_MODEL_PATH": "model.onnx"})


def test_env_factory_builds_hash_pinned_config(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    tokenizer = tmp_path / "tokenizer.json"
    model.write_bytes(b"model")
    tokenizer.write_bytes(b"tokenizer")

    verifier = semantic_verifier_from_env(
        {
            "FDAI_SEMANTIC_VERIFIER_MODEL_PATH": str(model),
            "FDAI_SEMANTIC_VERIFIER_TOKENIZER_PATH": str(tokenizer),
            "FDAI_SEMANTIC_VERIFIER_MODEL_SHA256": _sha(b"model"),
            "FDAI_SEMANTIC_VERIFIER_TOKENIZER_SHA256": _sha(b"tokenizer"),
            "FDAI_SEMANTIC_VERIFIER_MODEL_ID": "example/nli-onnx",
            "FDAI_SEMANTIC_VERIFIER_ENTAILMENT_INDEX": "2",
            "FDAI_SEMANTIC_VERIFIER_CONTRADICTION_INDEX": "0",
        }
    )

    assert verifier is not None


def test_config_rejects_non_pinned_hashes() -> None:
    with pytest.raises(ValueError, match="64 lowercase hex"):
        OnnxSemanticVerifierConfig(
            model_path=Path("model.onnx"),
            tokenizer_path=Path("tokenizer.json"),
            model_sha256="not-a-hash",
            tokenizer_sha256="0" * 64,
            model_id="example/nli-onnx",
            entailment_index=2,
            contradiction_index=0,
        )


def test_semantic_premise_is_bounded_and_omits_unknown_keys() -> None:
    premise = semantic_premise(
        {"routeId": "overview", "facts": ["x" * 100], "secret": "do-not-forward"},
        max_chars=60,
    )

    assert len(premise) == 60
    assert "secret" not in premise


async def test_disabled_shadow_does_not_call_provider() -> None:
    verification = verify_answer("Looks healthy.", {"routeId": "overview"}, locale="en")
    verifier = _Verifier(SemanticVerification("entailed", "test", "test-model", 1, 0.9, 0.05))

    result = await attach_semantic_shadow(
        verification,
        provisional="Looks healthy.",
        view_context={"routeId": "overview"},
        enabled=False,
        verifier=verifier,
    )

    assert result.semantic is None
    assert verifier.calls == []


async def test_structured_screen_claim_does_not_call_semantic_provider() -> None:
    verification = verify_answer(
        "The screen shows 12 events.",
        {"routeId": "overview", "facts": [{"key": "event_count", "value": 12}]},
        locale="en",
    )
    verifier = _Verifier(SemanticVerification("entailed", "test", "test-model", 1, 0.9, 0.05))

    result = await attach_semantic_shadow(
        verification,
        provisional="The screen shows 12 events.",
        view_context={"routeId": "overview"},
        enabled=True,
        verifier=verifier,
    )

    assert result.semantic is None
    assert verifier.calls == []


async def test_shadow_metadata_cannot_promote_or_revise_terminal_answer() -> None:
    verification = verify_answer("Looks healthy.", {"routeId": "overview"}, locale="en")
    verifier = _Verifier(SemanticVerification("contradicted", "test", "test-model", 2, 0.02, 0.95))

    result = await attach_semantic_shadow(
        verification,
        provisional="Looks healthy.",
        view_context={"routeId": "overview"},
        enabled=True,
        verifier=verifier,
    )

    assert result.status == verification.status
    assert result.answer == verification.answer
    assert result.semantic is not None
    assert result.semantic.verdict == "contradicted"
    assert verifier.calls[0][1] == "Looks healthy."


async def test_shadow_without_provider_is_unavailable() -> None:
    verification = verify_answer("Looks healthy.", {"routeId": "overview"}, locale="en")

    result = await attach_semantic_shadow(
        verification,
        provisional="Looks healthy.",
        view_context={"routeId": "overview"},
        enabled=True,
        verifier=None,
    )

    assert result.semantic is not None
    assert result.semantic.verdict == "unavailable"
    assert result.semantic.reason_code == "semantic_provider_not_configured"


async def test_shadow_timeout_is_unavailable() -> None:
    verification = verify_answer("Looks healthy.", {"routeId": "overview"}, locale="en")

    result = await attach_semantic_shadow(
        verification,
        provisional="Looks healthy.",
        view_context={"routeId": "overview"},
        enabled=True,
        verifier=_SlowVerifier(),
        timeout_seconds=0.001,
    )

    assert result.semantic is not None
    assert result.semantic.verdict == "unavailable"
    assert result.semantic.reason_code == "semantic_timeout"
