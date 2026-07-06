"""AzureOpenAICrossCheckModel - httpx-based T2 cross-check client.

Implements :class:`~aiopspilot.core.quality_gate.gate.CrossCheckModel` by
calling Azure OpenAI ``chat/completions`` with structured JSON output.
The response MUST contain ``action_type`` and ``params``; anything else
raises so the caller cannot silently accept a malformed proposal - this
is the "verifier is the authority" invariant from
``docs/roadmap/llm-strategy.md § T2 - Reasoning Tier``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_COGNITIVE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureOpenAICrossCheckModelConfig:
    """Endpoint + deployment binding for one cross-check capability."""

    endpoint: str
    deployment: str
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 30.0
    system_prompt: str = (
        "You are an AIOpsPilot cross-check reviewer. Given a candidate action, "
        "return ONLY a JSON object with fields: action_type (string), params "
        "(object). Do not include markdown fences or commentary. "
        "The verifier - not your prose - decides eligibility."
    )


class AzureOpenAICrossCheckModel:
    """Cross-check model backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAICrossCheckModelConfig,
    ) -> None:
        if not config.endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint MUST be an absolute https URL")
        if not config.deployment:
            raise ValueError("deployment MUST NOT be empty")
        if config.max_tokens < 1:
            raise ValueError("max_tokens MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not 0.0 <= config.temperature <= 2.0:
            raise ValueError("temperature MUST be in [0.0, 2.0]")
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAICrossCheckModelConfig] = config

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        token = await self._identity.get_token(_COGNITIVE_SCOPE)
        url = (
            self._config.endpoint.rstrip("/")
            + "/openai/deployments/"
            + self._config.deployment
            + "/chat/completions"
        )
        user_prompt = json.dumps(
            {
                "action_type": candidate.action_type,
                "target_resource_ref": candidate.target_resource_ref,
                "params": dict(candidate.params),
                "cited_rule_ids": list(candidate.cited_rule_ids),
            },
            sort_keys=True,
        )
        response = await self._http.post(
            url,
            params={"api-version": self._config.api_version},
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            json={
                "messages": [
                    {"role": "system", "content": self._config.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Azure OpenAI chat response missing choices[0].message.content: {body!r}"
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"cross-check model returned non-JSON content: {content!r}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"cross-check model MUST return a JSON object, got {type(parsed).__name__}"
            )

        action_type = parsed.get("action_type")
        params = parsed.get("params", {})
        if not isinstance(action_type, str) or not action_type:
            raise RuntimeError("cross-check response MUST carry a non-empty 'action_type' string")
        if not isinstance(params, dict):
            raise RuntimeError("cross-check response 'params' MUST be an object")
        return action_type, params


__all__ = ["AzureOpenAICrossCheckModel", "AzureOpenAICrossCheckModelConfig"]
