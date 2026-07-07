# METADATA
# title: Require a DDoS protection plan on network.vnet
# description: |
#   A network.vnet holding internet-exposed workloads MUST be attached
#   to a DDoS protection plan.
# custom:
#   rule_id: network.vnet.ddos-plan.required
#   severity: medium
#   category: security
package fdai.network.vnet_ddos_plan_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.vnet"
  input.resource.props.ddos_protection_plan_id == ""
}

deny_reason := "no_ddos_plan" if deny
