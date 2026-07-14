"""Production EventBus publisher composition for one-shot delivery jobs."""

from __future__ import annotations

import httpx

from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.shared.config.models import KafkaConfig


class EventPublisherContext:
    """Own the HTTP/identity/Event Hubs resources for a one-shot job."""

    def __init__(self, *, kafka: KafkaConfig) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
        )
        identity = ManagedIdentityWorkloadIdentity(http_client=self._http)
        self.bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=kafka.bootstrap_servers,
                dlq_suffix=kafka.topic_dlq_suffix,
            ),
        )

    async def __aenter__(self) -> EventHubsKafkaBus:
        return self.bus

    async def __aexit__(self, *_exc: object) -> None:
        await self.bus.close()
        await self._http.aclose()


__all__ = ["EventPublisherContext"]
