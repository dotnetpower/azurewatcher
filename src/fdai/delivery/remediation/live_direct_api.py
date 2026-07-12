"""Live (enforce) DirectApiExecutor adapter over kubectl/az.

This is the delivery-layer, **real-substrate** counterpart of the upstream
fake :class:`~fdai.shared.providers.testing.direct_api.RecordingDirectApiExecutor`.
It satisfies the core :class:`~fdai.shared.providers.direct_api.DirectApiExecutor`
Protocol by dispatching an ``ops.*`` remediation ActionType onto a live
cluster - so FDAI can actually *recover* a degraded workload (self-heal:
restart a service, scale a workload back out), not just detect the fault.

This is the remediation twin of the chaos
:mod:`fdai.delivery.chaos.live_injectors`: same subprocess-shim discipline,
opposite direction (heal, not perturb). ``core/`` never imports it - it is
wired at the composition root in place of the fake, exactly as
``delivery/azure/direct_api.py (fork territory)`` describes.

Safety contract preserved from the Protocol:

- **Promotion gate** - an ``ENFORCE`` request MUST carry the ``enforce``
  label or the adapter fail-closes with :class:`DirectApiPromotionError`
  (mirrors the PR publisher's enforce-label rule). A ``SHADOW`` request
  records intent and mutates nothing.
- **Idempotency** - an in-memory ledger keyed on ``idempotency_key``; a
  re-delivered request returns ``ALREADY_APPLIED`` and does not re-mutate.
- **Audit-shaped receipt** - every terminal path returns a
  :class:`DirectApiReceipt` the core executor records as one audit entry.

The core :class:`~fdai.core.executor.direct_api.DirectApiShadowExecutor`
stays the safety-invariant / lock / blast-radius gate in front of this
adapter; this class is only the substrate call.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Final

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)

_DEFAULT_TIMEOUT: Final[float] = 90.0


async def _run(
    cmd: Sequence[str],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    drop_azure_config_dir: bool = False,
) -> tuple[int, str, str]:
    """Run a subprocess, return (rc, stdout, stderr). Never shell=True."""

    env = None
    if drop_azure_config_dir:
        env = dict(os.environ)
        env.pop("AZURE_CONFIG_DIR", None)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class KubectlDirectApiExecutor(DirectApiExecutor):
    """Recover a degraded Kubernetes workload via kubectl (enforce path).

    Handlers keyed by ActionType name:

    - ``ops.restart-service`` -> ``kubectl rollout restart deployment/<ref>``
      (state-forward-only: the restart itself is the recovery).
    - ``ops.scale-out`` -> ``kubectl scale deployment/<ref>
      --replicas=<replica_count>`` (scale a degraded workload back out).

    ``target_resource_ref`` (from the rendered ActionType arguments, or the
    bare ``resource_ref``) names the deployment; the namespace/context are
    bound at construction so a request cannot cross the approved scope.
    """

    def __init__(self, *, context: str, namespace: str, kubectl: str = "kubectl") -> None:
        self._ctx = context
        self._ns = namespace
        self._kubectl = kubectl
        self._ledger: dict[str, DirectApiReceipt] = {}
        self._handlers: dict[
            str, Callable[[DirectApiRequest, str], Awaitable[DirectApiReceipt]]
        ] = {
            "ops.restart-service": self._restart_service,
            "ops.scale-out": self._scale_out,
        }

    def _base(self) -> list[str]:
        return [self._kubectl, "--context", self._ctx, "-n", self._ns]

    def _deployment(self, request: DirectApiRequest) -> str:
        ref = request.arguments.get("target_resource_ref") or request.resource_ref
        ref = str(ref)
        # Accept "ns/name" or "deployment/name" or bare "name".
        return ref.rsplit("/", 1)[-1]

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        # Promotion gate - enforce needs the explicit label; fail closed.
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode direct-api call requires an explicit 'enforce' label"
            )

        # Idempotency - a prior success short-circuits without re-mutating.
        prior = self._ledger.get(request.idempotency_key)
        if prior is not None and prior.outcome in (
            DirectApiOutcome.SUCCEEDED,
            DirectApiOutcome.ALREADY_APPLIED,
        ):
            return DirectApiReceipt(
                outcome=DirectApiOutcome.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                already_existed=True,
                detail=prior.detail,
            )

        handler = self._handlers.get(request.action_type_name)
        if handler is None:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.FAILED,
                receipt_ref="",
                detail=f"no_handler_for_action_type:{request.action_type_name}",
            )

        deployment = self._deployment(request)

        # Shadow records intent, mutates nothing (upstream default posture).
        if request.mode is Mode.SHADOW:
            receipt = DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:{request.action_type_name}:{deployment}",
                detail="shadow: intent recorded, no mutation",
            )
            self._ledger[request.idempotency_key] = receipt
            return receipt

        receipt = await handler(request, deployment)
        if receipt.outcome in (DirectApiOutcome.SUCCEEDED, DirectApiOutcome.ALREADY_APPLIED):
            self._ledger[request.idempotency_key] = receipt
        return receipt

    async def _restart_service(
        self, request: DirectApiRequest, deployment: str
    ) -> DirectApiReceipt:
        rc, out, err = await _run([*self._base(), "rollout", "restart", f"deployment/{deployment}"])
        if rc != 0:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.FAILED,
                receipt_ref="",
                rollback_succeeded=None,
                detail=f"rollout restart failed: {err.strip()[:160]}",
            )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=out.strip()[:120] or f"restarted:{deployment}",
            detail=f"restarted deployment/{deployment} (state-forward-only)",
        )

    async def _scale_out(self, request: DirectApiRequest, deployment: str) -> DirectApiReceipt:
        replicas = request.arguments.get("replica_count")
        if not isinstance(replicas, int) or replicas < 1:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.PRECONDITION_FAILED,
                receipt_ref="",
                detail="scale-out requires a positive integer replica_count",
            )
        rc, out, err = await _run(
            [*self._base(), "scale", f"deployment/{deployment}", f"--replicas={replicas}"]
        )
        if rc != 0:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.FAILED,
                receipt_ref="",
                detail=f"scale failed: {err.strip()[:160]}",
            )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=out.strip()[:120] or f"scaled:{deployment}:{replicas}",
            detail=f"scaled deployment/{deployment} to {replicas} replicas",
        )


__all__ = ["KubectlDirectApiExecutor"]
