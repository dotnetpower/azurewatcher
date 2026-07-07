# METADATA
# title: Require zone-redundant cache
# description: |
#   A cache MUST span at least two availability zones so a zone
#   outage does not evict the whole cache.
# custom:
#   rule_id: cache.zone-redundant
#   severity: high
#   category: reliability
package fdai.cache.zone_redundant

import rego.v1

default deny := false

deny if {
  input.resource.type == "cache"
  count(input.resource.props.zones) < 2
}

deny_reason := "cache_single_zone" if deny
