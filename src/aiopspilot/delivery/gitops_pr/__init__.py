"""GitOps PR-native remediation adapter (GitHub App / Azure DevOps).

Public exports (P1 W-3 Step 3e):

- :class:`~aiopspilot.delivery.gitops_pr.adapter.GitOpsPrAdapter` —
  GitHub REST implementation of the
  :class:`~aiopspilot.shared.providers.remediation_pr.RemediationPrPublisher`
  Protocol. Bound at the composition root; ``core/`` never imports it.
- :class:`~aiopspilot.delivery.gitops_pr.adapter.GitOpsPrConfig` /
  :class:`~aiopspilot.delivery.gitops_pr.adapter.GitOpsPrError` —
  adapter-level data types.
"""

from aiopspilot.delivery.gitops_pr.adapter import (
    GitOpsPrAdapter,
    GitOpsPrConfig,
    GitOpsPrError,
)

__all__ = [
    "GitOpsPrAdapter",
    "GitOpsPrConfig",
    "GitOpsPrError",
]
