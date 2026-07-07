"""Local dev entrypoint for the console read API.

Boots the Starlette app with :class:`UnsafeClaimsExtractor` (dev-only
JWT decoder) and an :class:`InMemoryConsoleReadModel` seeded with a few
synthetic entries so the console has something to render.

**Never wire this in production.** The env-var tripwire in
:func:`fdai.delivery.read_api.main.build_app` refuses to build a
dev-mode app unless ``FDAI_READ_API_DEV_MODE=1`` is set - this
module also asserts that at build time so a stray production revision
that boots it fails fast.

Usage (uvicorn's ``--factory`` flag calls :func:`app` at server start,
so importing this module during unrelated tooling - pytest collection,
mypy, IDE indexing - has no side effect)::

    FDAI_READ_API_DEV_MODE=1 \\
        uv run uvicorn 'fdai.delivery.read_api._local:app' \\
            --factory --port 8000
"""

from __future__ import annotations

import os

from starlette.applications import Starlette

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import (
    UnsafeClaimsExtractor,
    build_authenticator,
)
from fdai.delivery.read_api.live_control_loop import (
    ControlLoopEmitterUnavailable,
    build_control_loop_emitter,
)
from fdai.delivery.read_api.live_stream import LiveEmitter, LiveStreamConfig, SyntheticLiveEmitter
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import (
    HilQueueItem,
    InMemoryConsoleReadModel,
)
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.testing.sse import InMemorySseSink

_DEV_ENV = "FDAI_READ_API_DEV_MODE"


def _seed(read_model: InMemoryConsoleReadModel) -> None:
    """Seed audit entries (with trust tiers) + one pending HIL so the SPA renders data."""
    # (tier, action_kind, outcome, recorded_at time) - a realistic T0-heavy split.
    entries: tuple[tuple[str, str, str, str], ...] = (
        ("t0", "control_loop.abstain", "abstained_t0", "10:00:00"),
        ("t0", "enable-encryption", "shadow_pr_opened", "10:05:00"),
        ("t0", "tag-compliance", "shadow_pr_opened", "10:12:00"),
        ("t0", "control_loop.abstain", "abstained_t0", "10:20:00"),
        ("t0", "right-size-disk", "shadow_pr_opened", "10:31:00"),
        ("t0", "close-idle-endpoint", "shadow_pr_opened", "10:38:00"),
        ("t1", "reuse-learned-action", "shadow_pr_opened", "10:42:00"),
        ("t1", "correlate-incident", "matched_prior", "10:48:00"),
        ("t2", "root-cause-reasoning", "escalated_hil", "10:55:00"),
    )
    for i, (tier, action_kind, outcome, hhmmss) in enumerate(entries, start=1):
        read_model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-{i:012d}",
                "actor": "fdai.core.control_loop",
                "action_kind": action_kind,
                "mode": "shadow",
                "outcome": outcome,
                "tier": tier,
                "recorded_at": f"2026-07-06T{hhmmss}+00:00",
            }
        )
    read_model.record_hil_pending(
        HilQueueItem(
            idempotency_key="hil-dev-0001",
            event_id="00000000-0000-0000-0000-000000000010",
            action_kind="restrict-network-access",
            reason="blast-radius exceeds executor cap",
            requested_at="2026-07-06T10:10:00+00:00",
            correlation_id="corr-dev-0001",
        )
    )


def app() -> Starlette:
    """Factory. uvicorn invokes this once at server start with ``--factory``."""
    if os.environ.get(_DEV_ENV) != "1":
        raise RuntimeError(
            f"fdai.delivery.read_api._local requires {_DEV_ENV}=1; "
            "this module is a local dev entrypoint and MUST NOT boot in production."
        )
    read_model = InMemoryConsoleReadModel()
    _seed(read_model)
    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id="00000000-0000-0000-0000-000000000001",
            contributor_group_id="00000000-0000-0000-0000-000000000002",
            approver_group_id="00000000-0000-0000-0000-000000000003",
            owner_group_id="00000000-0000-0000-0000-000000000004",
            break_glass_group_id="00000000-0000-0000-0000-000000000005",
        )
    )
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=resolver,
    )
    return build_app(
        authenticator=authenticator,
        read_model=read_model,
        config=ReadApiConfig(
            dev_mode=True,
            cors_allow_origins=(
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:8090",
                "http://localhost:8090",
            ),
            live_stream=_build_live_stream_config(),
        ),
    )


def _build_live_stream_config() -> LiveStreamConfig:
    """Compose the live-stream config for the dev harness.

    Preferred: attach a real :class:`ControlLoopLiveEmitter` so the
    console shows stage frames produced by the actual pipeline. If the
    shipped rule catalog cannot be composed (missing files, YAML errors)
    the emitter factory raises :class:`ControlLoopEmitterUnavailable`
    and we fall back to :class:`SyntheticLiveEmitter`, which emits the
    same wire format from a hardcoded distribution so the FE is never
    dark.

    The sink is created once here so it can be shared by the route
    consumer and (in a future round) any additional publisher we bolt
    on the same channel.
    """

    sink: SseSink = InMemorySseSink()
    channel = "aw.pipeline.stages"

    def _factory(sink_arg: SseSink, channel_arg: str) -> LiveEmitter:
        try:
            return build_control_loop_emitter(
                sink_arg,
                channel_arg,
                events_per_second=8.0,
            )
        except ControlLoopEmitterUnavailable:
            # Rule catalog not available; keep the console populated
            # with the hardcoded distribution.
            return SyntheticLiveEmitter(sink=sink_arg, channel=channel_arg)

    return LiveStreamConfig(
        path="/live/stream",
        channel=channel,
        sink=sink,
        emitter_factory=_factory,
    )
