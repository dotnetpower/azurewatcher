# METADATA
# title: Require zone redundancy on compute.vm-scale-set
# description: |
#   A compute.vm-scale-set MUST span at least two availability zones
#   to survive a single-zone outage.
# custom:
#   rule_id: compute.vm-scale-set.zone-redundancy
#   severity: high
#   category: reliability
package fdai.compute.vmss_zone_redundancy

import rego.v1

default deny := false

deny if {
  input.resource.type == "compute.vm-scale-set"
  count(input.resource.props.zones) < 2
}

deny_reason := "single_zone_scale_set" if deny
