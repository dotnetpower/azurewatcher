from __future__ import annotations

import httpx
import pytest

from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.runtime.bootstrap import _build_runtime_workload_identity
from fdai.shared.config.runtime_flags import pantheon_start_enabled


def test_pantheon_starts_by_default() -> None:
    assert pantheon_start_enabled({}) is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_pantheon_requires_explicit_disable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_pantheon_accepts_explicit_enable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is True


async def test_dev_runtime_uses_explicit_azure_cli_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, AsyncAzureCliWorkloadIdentity)


async def test_non_dev_runtime_keeps_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, ManagedIdentityWorkloadIdentity)


async def test_case_history_runtime_requires_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.delenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", raising=False)

    async with httpx.AsyncClient() as http_client:
        with pytest.raises(RuntimeError, match="FDAI_CASE_HISTORY_MI_CLIENT_ID"):
            _build_runtime_workload_identity(
                http_client,
                client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
                require_client_id=True,
            )


async def test_case_history_runtime_selects_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"access_token": "token", "expires_on": "4102444800"},
        )

    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.setenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", "case-history-client")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        identity = _build_runtime_workload_identity(
            http_client,
            client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
            require_client_id=True,
        )
        await identity.get_token("https://storage.azure.com/")

    assert captured[0].url.params["client_id"] == "case-history-client"
