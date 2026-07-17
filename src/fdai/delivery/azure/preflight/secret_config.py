"""Value-blind Key Vault secret existence checks for deployment preflight."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, urlparse

import httpx

from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_AUDIENCE: Final[str] = "https://vault.azure.net/.default"
_API_VERSION: Final[str] = "7.4"
_TIMEOUT_SECONDS: Final[float] = 20.0
_SECRET_NAME = re.compile(r"^[A-Za-z0-9-]{1,127}$")


class AzureSecretProbeError(RuntimeError):
    """A Key Vault existence check could not produce a complete result."""


@dataclass(frozen=True, slots=True)
class AzureSecretProbeConfig:
    vault_endpoint: str
    required_secret_names: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlparse(self.vault_endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or not parsed.hostname.endswith(".vault.azure.net")
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("vault_endpoint MUST be an Azure Key Vault HTTPS origin")
        if not self.required_secret_names:
            raise ValueError("required_secret_names MUST NOT be empty")
        if len(self.required_secret_names) > 64:
            raise ValueError("required_secret_names MUST contain at most 64 entries")
        if any(_SECRET_NAME.fullmatch(name) is None for name in self.required_secret_names):
            raise ValueError("required secret names MUST use the Key Vault name format")


class AzureSecretConfigProbe:
    """Check required secret references without reading response bodies or values."""

    def __init__(
        self,
        *,
        config: AzureSecretProbeConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.SECRET_CONFIG

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        del target
        token = await self._identity.get_token(_AUDIENCE)
        findings: list[ProbeFinding] = []
        for name in sorted(set(self._config.required_secret_names)):
            status = await self._status(name, token.token)
            if status == 404:
                findings.append(self._missing_finding(name))
            elif status >= 400:
                raise AzureSecretProbeError(f"Key Vault secret metadata returned HTTP {status}")
        return tuple(findings)

    async def _status(self, name: str, token: str) -> int:
        url = (
            f"{self._config.vault_endpoint.rstrip('/')}/secrets/{quote(name, safe='')}"
            f"?api-version={_API_VERSION}"
        )
        try:
            async with self._http.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=_TIMEOUT_SECONDS,
            ) as response:
                return response.status_code
        except httpx.HTTPError as exc:
            raise AzureSecretProbeError("Key Vault secret metadata request failed") from exc

    @staticmethod
    def _missing_finding(name: str) -> ProbeFinding:
        reference = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
        return ProbeFinding(
            id=f"missing-secret-ref:{reference}",
            category=ProbeCategory.SECRET_CONFIG,
            severity=FindingSeverity.BLOCKING,
            title="a required secret reference is missing",
            evidence=ProbeEvidence(
                source=f"key-vault:secret-metadata:{reference}",
                detail="the required secret metadata endpoint returned not found",
            ),
            resolution=ProbeResolution(
                kind=ResolutionKind.MANUAL,
                guidance=(
                    "create the required secret through the approved secret workflow "
                    "and rerun preflight"
                ),
            ),
        )


__all__ = [
    "AzureSecretConfigProbe",
    "AzureSecretProbeConfig",
    "AzureSecretProbeError",
]
