"""In-memory :class:`RemediationPrPublisher` for tests + local development.

Captures every publish call in an append-only list so a test can assert
on the exact intent the executor produced (title, body, patch, labels).
Idempotency is honored: a second publish for the same
``idempotency_key`` returns the same receipt with ``already_existed=True``
and does NOT duplicate the recorded entry — this matches the contract in
``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Remediation PR``.
"""

from __future__ import annotations

from itertools import count

from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)


class RecordingRemediationPrPublisher(RemediationPrPublisher):
    """A fake publisher that keeps every intent in-memory.

    Tests treat it as the source of truth for "what would the delivery
    layer have posted"; the executor never sees a raw HTTP client.
    """

    def __init__(self) -> None:
        self._records: list[RemediationPr] = []
        self._by_key: dict[str, PublishReceipt] = {}
        self._counter = count(1)

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        if pr.mode is not Mode.SHADOW:
            # The publisher rejects an enforce intent that has not been
            # promoted through the ActionType promotion_gate; the
            # executor MUST NOT rely on the publisher to allow it.
            if "enforce" not in pr.labels:
                raise ValueError(
                    "enforce-mode PR requires an explicit 'enforce' label (P1 promotion contract)"
                )

        prior = self._by_key.get(pr.idempotency_key)
        if prior is not None:
            return PublishReceipt(pr_ref=prior.pr_ref, url=prior.url, already_existed=True)

        pr_ref = f"pr-{next(self._counter)}"
        receipt = PublishReceipt(pr_ref=pr_ref, url=f"https://example.com/pr/{pr_ref}")
        self._by_key[pr.idempotency_key] = receipt
        self._records.append(pr)
        return receipt

    # ------------------------------------------------------------------
    # Assertion helpers (test-only)
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[RemediationPr, ...]:
        """Every publish call the executor made, in order."""
        return tuple(self._records)

    def find(self, idempotency_key: str) -> RemediationPr | None:
        for record in self._records:
            if record.idempotency_key == idempotency_key:
                return record
        return None


__all__ = ["RecordingRemediationPrPublisher"]
