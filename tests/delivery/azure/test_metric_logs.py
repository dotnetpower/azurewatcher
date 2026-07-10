"""httpx-mocked tests for the Azure Monitor Logs metric adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.metric_logs import (
    AzureMonitorLogsConfig,
    AzureMonitorLogsMetricProvider,
    MetricKqlTemplate,
)
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


_TEMPLATE = MetricKqlTemplate(
    kql="AppRequests | summarize v=avg(DurationMs) by bin(TimeGenerated, 1m), Resource",
    value_column="v",
    label_columns=("Resource",),
)

_METRIC = "http.server.request.duration"


async def _drain(
    provider: AzureMonitorLogsMetricProvider, metric: str = _METRIC, **kw: object
) -> list:
    return [p async for p in provider.query(MetricQuery(metric_name=metric, **kw))]  # type: ignore[arg-type]


def _config(**overrides: object) -> AzureMonitorLogsConfig:
    base = dict(
        workspace_id="00000000-0000-0000-0000-000000000001",
        queries={"http.server.request.duration": _TEMPLATE},
    )
    base.update(overrides)
    return AzureMonitorLogsConfig(**base)  # type: ignore[arg-type]


def _table(rows: list[list[object]]) -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "TimeGenerated", "type": "datetime"},
                    {"name": "v", "type": "real"},
                    {"name": "Resource", "type": "string"},
                ],
                "rows": rows,
            }
        ]
    }


def _provider(handler, cfg: AzureMonitorLogsConfig | None = None) -> tuple[
    AzureMonitorLogsMetricProvider, httpx.AsyncClient
]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorLogsMetricProvider(
        config=cfg or _config(),
        identity=_StaticIdentity(),
        http_client=client,
    )
    return provider, client


@pytest.mark.asyncio
async def test_query_maps_rows_to_points_in_chronological_order() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_table(
                [
                    ["2026-07-10T00:02:00Z", 12.5, "vm-b"],
                    ["2026-07-10T00:01:00Z", 5.0, "vm-a"],
                ]
            ),
        )

    provider, client = _provider(handler)
    try:
        points = await _drain(provider)
    finally:
        await client.aclose()

    assert [p.value for p in points] == [5.0, 12.5]  # sorted by timestamp
    assert points[0].labels == {"Resource": "vm-a"}
    assert points[0].metric_name == "http.server.request.duration"
    # bearer token + workspace path threaded through
    assert captured[0].headers["Authorization"] == "Bearer test-token"
    assert "/workspaces/00000000-0000-0000-0000-000000000001/query" in str(captured[0].url)


@pytest.mark.asyncio
async def test_labels_filter_is_applied_in_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_table(
                [
                    ["2026-07-10T00:01:00Z", 5.0, "vm-a"],
                    ["2026-07-10T00:02:00Z", 9.0, "vm-b"],
                ]
            ),
        )

    provider, client = _provider(handler)
    try:
        points = [
            p
            async for p in provider.query(
                MetricQuery(
                    metric_name="http.server.request.duration",
                    labels={"Resource": "vm-b"},
                )
            )
        ]
    finally:
        await client.aclose()

    assert len(points) == 1
    assert points[0].labels == {"Resource": "vm-b"}


@pytest.mark.asyncio
async def test_timespan_included_only_when_both_bounds_present() -> None:
    captured: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_table([]))

    provider, client = _provider(handler)
    since = datetime(2026, 7, 10, tzinfo=UTC)
    until = since + timedelta(hours=1)
    try:
        _ = [p async for p in provider.query(
            MetricQuery(metric_name="http.server.request.duration", since=since, until=until)
        )]
        _ = [p async for p in provider.query(
            MetricQuery(metric_name="http.server.request.duration", since=since)
        )]
    finally:
        await client.aclose()

    assert "timespan" in captured[0]
    assert captured[0]["timespan"] == f"{since.isoformat()}/{until.isoformat()}"
    assert "timespan" not in captured[1]  # single bound -> KQL time filter governs


@pytest.mark.asyncio
async def test_unknown_metric_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not reached
        return httpx.Response(200, json=_table([]))

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="no KQL template"):
            _ = [p async for p in provider.query(MetricQuery(metric_name="unknown.metric"))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_error_status_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden: workspace access denied")

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="HTTP 403"):
            await _drain(provider)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_column_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [{"name": "TimeGenerated", "type": "datetime"}],
                        "rows": [["2026-07-10T00:01:00Z"]],
                    }
                ]
            },
        )

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="lacks required column 'v'"):
            await _drain(provider)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_max_rows_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        rows = [["2026-07-10T00:01:00Z", 1.0, "vm-a"] for _ in range(3)]
        return httpx.Response(200, json=_table(rows))

    provider, client = _provider(handler, _config(max_rows=2))
    try:
        with pytest.raises(MetricProviderError, match="over the max_rows cap"):
            await _drain(provider)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_non_numeric_value_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_table([["2026-07-10T00:01:00Z", "not-a-number", "vm-a"]]))

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="non-numeric metric value"):
            await _drain(provider)
    finally:
        await client.aclose()


def test_config_rejects_empty_workspace_and_bad_max_rows() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        AzureMonitorLogsConfig(workspace_id="", queries={})
    with pytest.raises(ValueError, match="max_rows"):
        AzureMonitorLogsConfig(workspace_id="w", queries={}, max_rows=0)
