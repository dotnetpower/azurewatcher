"""Publish one mechanical forecast-evaluation tick to governed raw ingress."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime

from fdai.composition import default_container_from_env
from fdai.delivery.event_publisher import EventPublisherContext

_LOGGER = logging.getLogger("fdai.delivery.forecast_tick_cli")
_BUCKET_SECONDS = 60


async def _tick() -> int:
    container = default_container_from_env()
    now = datetime.now(UTC)
    tick_id = forecast_tick_id(now)
    async with EventPublisherContext(kafka=container.config.kafka) as event_bus:
        await event_bus.publish(
            container.config.kafka.topic_events,
            tick_id,
            {
                "event_id": tick_id,
                "idempotency_key": tick_id,
                "correlation_id": tick_id,
                "source": "forecast-evaluation-scheduler",
                "event_type": "forecast.evaluation_due",
                "attributes": {"emitted_at": now.isoformat()},
            },
        )
    _LOGGER.info("forecast_evaluation_tick_published", extra={"tick_id": tick_id})
    return 0


def forecast_tick_id(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("forecast evaluation tick MUST be timezone-aware")
    bucket = int(now.timestamp()) // _BUCKET_SECONDS
    return f"forecast-evaluation:{bucket}"


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_tick())
    except Exception:
        _LOGGER.exception("forecast_evaluation_tick_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["forecast_tick_id", "main"]
