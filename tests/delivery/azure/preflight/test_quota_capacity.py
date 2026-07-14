"""httpx-mocked tests for the live Azure quota probe (issue #13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.preflight import (
    ArmClientConfig,
    AzureArmClient,
    AzurePreflightError,
    AzureQuotaProbe,
    AzureQuotaProbeConfig,
    QuotaCheck,
)
from fdai.shared.providers.feasibility_probe import (
    PreflightTarget,
    ProbeCategory,
    ResolutionKind,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_SUB = "00000000-0000-0000-0000-000000000001"
_LOCATION = "koreacentral"
_TARGET = PreflightTarget(scope="rg:app")


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - fake token, not a secret
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _usages(*rows: tuple[str, int, int]) -> dict[str, object]:
    return {
        "value": [
            {"name": {"value": name, "localizedValue": name}, "currentValue": cur, "limit": lim}
            for name, cur, lim in rows
        ]
    }


def _probe(payload: dict[str, object], checks: tuple[QuotaCheck, ...]) -> AzureQuotaProbe:
    def handle(request: httpx.Request) -> httpx.Response:
        assert "/usages" in request.url.path
        return httpx.Response(200, json=payload)

    client = AzureArmClient(
        identity=_StaticIdentity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        config=ArmClientConfig(),
    )
    return AzureQuotaProbe(
        client=client,
        config=AzureQuotaProbeConfig(subscription_id=_SUB, location=_LOCATION, checks=checks),
    )


async def test_quota_at_limit_with_required_headroom_blocks() -> None:
    probe = _probe(
        _usages(("standardDSv3Family", 8, 10)),
        (QuotaCheck("standardDSv3Family", required=4),),
    )
    findings = await probe.evaluate(_TARGET)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category is ProbeCategory.QUOTA_CAPACITY
    assert finding.evidence.source == f"quota:standardDSv3Family@{_LOCATION}"
    assert finding.resolution.kind is ResolutionKind.MANUAL


async def test_quota_with_headroom_is_clear() -> None:
    probe = _probe(
        _usages(("standardDSv3Family", 2, 10)),
        (QuotaCheck("standardDSv3Family", required=4),),
    )
    assert await probe.evaluate(_TARGET) == ()


async def test_quota_name_is_case_insensitive() -> None:
    probe = _probe(
        _usages(("cores", 100, 100)),
        (QuotaCheck("Cores", required=1),),
    )
    findings = await probe.evaluate(_TARGET)
    assert len(findings) == 1


async def test_unknown_quota_name_is_skipped() -> None:
    probe = _probe(
        _usages(("standardDSv3Family", 9, 10)),
        (QuotaCheck("standardNCv3Family", required=1),),
    )
    assert await probe.evaluate(_TARGET) == ()


async def test_arm_error_propagates_fail_closed() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="throttled")

    client = AzureArmClient(
        identity=_StaticIdentity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        config=ArmClientConfig(),
    )
    probe = AzureQuotaProbe(
        client=client,
        config=AzureQuotaProbeConfig(
            subscription_id=_SUB, location=_LOCATION, checks=(QuotaCheck("cores"),)
        ),
    )
    with pytest.raises(AzurePreflightError):
        await probe.evaluate(_TARGET)


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        AzureQuotaProbeConfig(subscription_id="", location=_LOCATION, checks=(QuotaCheck("c"),))
    with pytest.raises(ValueError):
        AzureQuotaProbeConfig(subscription_id=_SUB, location="", checks=(QuotaCheck("c"),))
    with pytest.raises(ValueError):
        AzureQuotaProbeConfig(subscription_id=_SUB, location=_LOCATION, checks=())
    with pytest.raises(ValueError):
        QuotaCheck("", required=1)
    with pytest.raises(ValueError):
        QuotaCheck("cores", required=0)
