"""Scheduler tick entry point - out-of-band driver for the scheduler.

A Container Apps Job (cron) launches this module once per scheduled fire
(``infra/modules/compute/container-apps/scheduler_job.tf``). It lives under
``delivery/`` (not ``core/``) because it wires the concrete
:class:`~fdai.delivery.persistence.postgres_scheduler_store.PostgresScheduleStore`
adapter - ``core/`` never imports an adapter; a composition-root entry point
does.

It reads the persistent schedule store (shared with the operator console)
from ``FDAI_SCHEDULE_STORE_DSN`` and computes which tasks are due with the
pure :func:`~fdai.core.scheduler.service.compute_due`.

Upstream-safe binding (mirrors ``core/measurement/runners_cli.py``)
------------------------------------------------------------------

Publishing a due task's synthetic event requires the concrete event-bus
adapter (Kafka), which a fork binds at the composition root. Upstream this
entry point runs a **shadow dry-run**: it loads the persistent store,
computes the due set, and logs the task ids that WOULD fire, then exits
``0`` without publishing. A fork swaps the dry-run for
``await SchedulerService(store, bus).run_once(now=now)`` so the same cron
publishes onto the ingest topic - the standard trust-router + risk-gate
still govern any resulting action. The scheduler never executes a change.

Exit codes
----------

- ``0`` - the tick completed (dry-run listed the due set), or no store DSN
  is configured (nothing to do upstream).
- ``3`` - an unexpected error; safe to page.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from fdai.composition import default_container_from_env
from fdai.core.scheduler.service import SchedulerService
from fdai.delivery.event_publisher import EventPublisherContext
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)

_LOGGER = logging.getLogger("fdai.delivery.scheduler_tick_cli")

_ENV_DSN = "FDAI_SCHEDULE_STORE_DSN"


async def _tick() -> int:
    dsn = os.environ.get(_ENV_DSN, "").strip()
    if not dsn:
        _LOGGER.info("scheduler_tick_no_store", extra={"reason": f"{_ENV_DSN} unset"})
        return 0

    store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    container = default_container_from_env()
    async with EventPublisherContext(kafka=container.config.kafka) as event_bus:
        report = await SchedulerService(
            store=store,
            event_bus=event_bus,
            topic=container.config.kafka.topic_events,
        ).run_once()
    _LOGGER.info(
        "scheduler_tick_complete",
        extra={
            "fired": report.fired,
            "publish_errors": len(report.publish_errors),
        },
    )
    return 3 if report.publish_errors else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return asyncio.run(_tick())
    except Exception:  # noqa: BLE001 - top-level job guard; log + non-zero exit
        _LOGGER.exception("scheduler_tick_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
