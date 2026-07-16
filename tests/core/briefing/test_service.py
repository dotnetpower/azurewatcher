from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.briefing import (
    BriefingContent,
    BriefingCoordinator,
    BriefingSchedulerService,
    OpeningBriefingService,
    next_cron_run,
)
from fdai.core.report_feed import ReportFeed, ReportSignal, StaticSignalSource
from fdai.core.report_feed.models import ReportCategory, SignalKind
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.briefing import (
    BriefingDeliveryMode,
    BriefingRunStatus,
    BriefingSpec,
    BriefingSubscription,
    ConversationPolicyKind,
    ConversationPolicyRecord,
)
from fdai.shared.providers.testing.briefing import (
    InMemoryBriefingRunStore,
    InMemoryBriefingSubscriptionStore,
    InMemoryConversationPolicyStore,
)

NOW = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)


def _coordinator() -> BriefingCoordinator:
    signal = ReportSignal(
        signal_id="signal-1",
        kind=SignalKind.INVESTIGATION,
        category=ReportCategory.WORKLOAD,
        severity=Severity.HIGH,
        resource_ref="resource-1",
        title="Database latency",
        detail="Latency exceeded the recorded threshold.",
        occurred_at=NOW,
        evidence_refs=("audit:1",),
    )
    return BriefingCoordinator(report_feed=ReportFeed((StaticSignalSource("signals", (signal,)),)))


async def test_opening_briefing_runs_once_per_conversation_and_policy_revision() -> None:
    policies = InMemoryConversationPolicyStore()
    runs = InMemoryBriefingRunStore()
    await policies.put(
        ConversationPolicyRecord(
            policy_id="opening",
            principal_id="principal-a",
            kind=ConversationPolicyKind.OPENING_BRIEFING,
            enabled=True,
            revision=0,
            confirmed_at=NOW,
            source_turn_id="turn-1",
            briefing_spec=BriefingSpec(),
        )
    )
    service = OpeningBriefingService(
        policies=policies,
        runs=runs,
        coordinator=_coordinator(),
        clock=lambda: NOW,
    )

    first = await service.open(principal_id="principal-a", conversation_id="conversation-1")
    second = await service.open(principal_id="principal-a", conversation_id="conversation-1")
    assert first is not None
    assert second == first
    assert first.item_count == 1
    assert first.evidence_refs == ("audit:1",)


async def test_scheduler_creates_idempotent_run_and_advances_subscription() -> None:
    subscriptions = InMemoryBriefingSubscriptionStore()
    runs = InMemoryBriefingRunStore()
    created = await subscriptions.create(
        BriefingSubscription(
            subscription_id="subscription-1",
            principal_id="principal-a",
            name="Morning briefing",
            spec=BriefingSpec(),
            cron_expression="0 7 * * *",
            timezone="Asia/Seoul",
            delivery_modes=(BriefingDeliveryMode.IN_APP,),
            enabled=True,
            next_run_at=NOW,
            created_at=NOW,
        )
    )
    service = BriefingSchedulerService(
        subscriptions=subscriptions,
        runs=runs,
        coordinator=_coordinator(),
        worker_id="worker-a",
        clock=lambda: NOW,
    )

    result = await service.run_once()
    assert len(result) == 1
    assert result[0].subscription_id == created.subscription_id
    assert await service.run_once() == ()
    advanced = await subscriptions.list_for_principal(principal_id="principal-a")
    assert advanced[0].next_run_at > NOW


async def test_scheduler_records_late_run_as_failed_and_advances() -> None:
    subscriptions = InMemoryBriefingSubscriptionStore()
    runs = InMemoryBriefingRunStore()
    await subscriptions.create(
        BriefingSubscription(
            subscription_id="late",
            principal_id="principal-a",
            name="Late briefing",
            spec=BriefingSpec(),
            cron_expression="0 7 * * *",
            timezone="Asia/Seoul",
            delivery_modes=(BriefingDeliveryMode.IN_APP,),
            enabled=True,
            next_run_at=NOW - timedelta(hours=2),
            created_at=NOW - timedelta(days=1),
            max_lateness_seconds=60,
        )
    )
    service = BriefingSchedulerService(
        subscriptions=subscriptions,
        runs=runs,
        coordinator=_coordinator(),
        worker_id="worker-a",
        clock=lambda: NOW,
    )

    result = await service.run_once()

    assert len(result) == 1
    assert result[0].status is BriefingRunStatus.FAILED
    assert result[0].source_errors == ("missed_by_seconds:7200",)
    advanced = await subscriptions.list_for_principal(principal_id="principal-a")
    assert advanced[0].next_run_at > NOW


async def test_scheduler_isolates_one_generation_failure() -> None:
    class FlakyCoordinator(BriefingCoordinator):
        def __init__(self) -> None:
            super().__init__(report_feed=ReportFeed())
            self.calls = 0

        async def generate(self, *, spec: BriefingSpec, now: datetime) -> BriefingContent:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("source down")
            return await _coordinator().generate(spec=spec, now=now)

    subscriptions = InMemoryBriefingSubscriptionStore()
    runs = InMemoryBriefingRunStore()
    base = BriefingSubscription(
        subscription_id="a-fails",
        principal_id="principal-a",
        name="First",
        spec=BriefingSpec(),
        cron_expression="0 7 * * *",
        timezone="Asia/Seoul",
        delivery_modes=(BriefingDeliveryMode.IN_APP,),
        enabled=True,
        next_run_at=NOW,
        created_at=NOW,
    )
    await subscriptions.create(base)
    await subscriptions.create(replace(base, subscription_id="b-succeeds", name="Second"))
    service = BriefingSchedulerService(
        subscriptions=subscriptions,
        runs=runs,
        coordinator=FlakyCoordinator(),
        worker_id="worker-a",
        clock=lambda: NOW,
    )

    result = await service.run_once()

    assert [run.status for run in result] == [
        BriefingRunStatus.FAILED,
        BriefingRunStatus.DELIVERED,
    ]


def test_next_cron_run_respects_iana_timezone_and_dst() -> None:
    before_dst = datetime(2026, 3, 6, 15, 0, tzinfo=UTC)
    first = next_cron_run("0 7 * * *", "America/New_York", after=before_dst)
    second = next_cron_run("0 7 * * *", "America/New_York", after=first)
    assert first.hour == 12
    assert second.hour == 11
