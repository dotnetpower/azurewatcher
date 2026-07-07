"""deploy-preflight - collect deployment blockers before an apply.

Before the executor emits a remediation PR (and as a standalone check for
human-authored deploys), the preflight pass runs a set of deterministic
:class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
implementations over a :class:`PreflightTarget` and assembles a single
grounded :class:`DeploymentReadinessReport`. It is the ``what-if`` verifier
generalized from per-action to per-deployment.

Full design: ``docs/roadmap/deployment-preflight.md``.
"""

from __future__ import annotations

from fdai.core.deploy_preflight.analyzer import PreflightAnalyzer
from fdai.core.deploy_preflight.check_publish import (
    PreflightCheckOutcome,
    PreflightCheckResult,
    publish_preflight_check,
)
from fdai.core.deploy_preflight.environment_profile import (
    DeploymentEnvironmentProfile,
    DeploymentEnvironmentProfileCache,
    apply_inventory_delta,
    build_profile,
)
from fdai.core.deploy_preflight.report import (
    DeploymentReadinessReport,
    ReadinessVerdict,
)

__all__ = [
    "DeploymentEnvironmentProfile",
    "DeploymentEnvironmentProfileCache",
    "DeploymentReadinessReport",
    "PreflightAnalyzer",
    "PreflightCheckOutcome",
    "PreflightCheckResult",
    "ReadinessVerdict",
    "apply_inventory_delta",
    "build_profile",
    "publish_preflight_check",
]
