# METADATA
# title: Require multi-zone kubernetes-node-pool
# description: |
#   A kubernetes-node-pool MUST span at least two availability zones
#   so a single-zone outage does not evict the whole pool.
# custom:
#   rule_id: kubernetes-node-pool.multi-zone
#   severity: high
#   category: reliability
package aiopspilot.kubernetes.node_pool_multi_zone

import rego.v1

default deny := false

deny if {
  input.resource.type == "kubernetes-node-pool"
  count(input.resource.props.availability_zones) < 2
}

deny_reason := "single_zone_node_pool" if deny
