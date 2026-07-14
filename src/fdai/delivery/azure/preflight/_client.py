"""Shared ARM client for the live Azure preflight probes.

The preflight probe adapters under ``delivery/azure/preflight/`` all talk to
the Azure Resource Manager control plane the same way the other Azure adapters
do (``arg_query`` / ``deployment_history``): an injected
:class:`httpx.AsyncClient` for transport and an injected
:class:`~fdai.shared.providers.workload_identity.WorkloadIdentity` for a
short-lived bearer token. No ``azure-identity``, no ``DefaultAzureCredential``,
no cloud SDK - ``core/`` never sees this module.

Read-only and fail-closed: every call is a ``GET``, a non-2xx or non-JSON
response raises :class:`AzurePreflightError`, and the caller (the
``PreflightAnalyzer``) turns a raised probe into a fail-closed pass rather than
a false ``clear``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARM_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PAGES: Final[int] = 32
_ERROR_SNIPPET_MAX: Final[int] = 200


class AzurePreflightError(RuntimeError):
    """Raised when an ARM preflight request fails or returns unusable output.

    The message is safe to log: it carries the failing path, the HTTP status,
    and a short-truncated reason, never a raw response body or a token.
    """


@dataclass(frozen=True, slots=True)
class ArmClientConfig:
    """Endpoint + auth + limits for :class:`AzureArmClient`."""

    arm_endpoint: str = _DEFAULT_ARM_ENDPOINT
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_pages: int = _DEFAULT_MAX_PAGES

    def __post_init__(self) -> None:
        parsed = urlparse(self.arm_endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("arm_endpoint MUST be an absolute HTTPS URL")
        if not self.audience.startswith("https://"):
            raise ValueError("audience MUST be an HTTPS URI")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if self.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")


class AzureArmClient:
    """A minimal read-only ARM GET client bound to a WorkloadIdentity."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: ArmClientConfig | None = None,
    ) -> None:
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[ArmClientConfig] = config or ArmClientConfig()

    async def get_json(
        self, path: str, *, api_version: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """GET one ARM resource path and return the parsed JSON object."""
        url = self._url(path, api_version=api_version, params=params)
        return await self._get(url, path=path)

    async def get_values(
        self, path: str, *, api_version: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """GET a paged ARM collection and return the concatenated ``value`` list.

        Follows ``nextLink`` up to :attr:`ArmClientConfig.max_pages`. A page
        without a ``value`` array raises :class:`AzurePreflightError`.
        """
        url: str | None = self._url(path, api_version=api_version, params=params)
        collected: list[dict[str, Any]] = []
        pages = 0
        while url is not None:
            if pages >= self._config.max_pages:
                raise AzurePreflightError(
                    f"ARM collection {path!r} exceeded max_pages={self._config.max_pages}"
                )
            pages += 1
            payload = await self._get(url, path=path)
            value = payload.get("value")
            if not isinstance(value, list):
                raise AzurePreflightError(f"ARM payload for {path!r} missing 'value' array")
            collected.extend(item for item in value if isinstance(item, dict))
            next_link = payload.get("nextLink")
            url = next_link if isinstance(next_link, str) and next_link else None
        return collected

    def _url(self, path: str, *, api_version: str, params: dict[str, str] | None) -> str:
        query = f"api-version={api_version}"
        if params:
            extra = "&".join(f"{key}={value}" for key, value in params.items())
            query = f"{query}&{extra}"
        return f"{self._config.arm_endpoint}{path}?{query}"

    async def _get(self, url: str, *, path: str) -> dict[str, Any]:
        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
        }
        try:
            response = await self._http.get(
                url, headers=headers, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise AzurePreflightError(f"ARM request failed for {path!r}: {exc}") from exc
        if response.status_code >= 400:
            snippet = response.text[:_ERROR_SNIPPET_MAX].replace("\n", " ")
            raise AzurePreflightError(
                f"ARM returned HTTP {response.status_code} for {path!r}: {snippet!r}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AzurePreflightError(f"ARM returned non-JSON for {path!r}") from exc
        if not isinstance(payload, dict):
            raise AzurePreflightError(f"ARM payload for {path!r} is not a JSON object")
        return payload


__all__ = ["ArmClientConfig", "AzureArmClient", "AzurePreflightError"]
