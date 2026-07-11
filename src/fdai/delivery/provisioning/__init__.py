"""Provisioning bridges - map infra tooling output into ``provision.*`` events.

Surface **A** (Day-1 bootstrap) of the Genesis provisioning experience. The
console does not exist yet during the first apply, so this package turns a
local ``terraform apply -json`` run into the same ``provision.*`` stream the
in-product surface emits, letting the Genesis screen run locally with a
truthful rhythm.
"""

from __future__ import annotations

from fdai.delivery.provisioning.serve import aiter_json_lines, pump_provision_events
from fdai.delivery.provisioning.terraform_bridge import (
    TerraformProvisionBridge,
    console_url_from_outputs,
    parse_json_line,
)

__all__ = [
    "TerraformProvisionBridge",
    "aiter_json_lines",
    "console_url_from_outputs",
    "parse_json_line",
    "pump_provision_events",
]
