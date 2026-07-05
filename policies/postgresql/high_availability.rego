# METADATA
# title: Require zone-redundant HA on postgresql-server
# description: |
#   A postgresql-server MUST run in zone-redundant HA mode to survive
#   a zone outage without operator action.
# custom:
#   rule_id: postgresql-server.high-availability
#   severity: high
#   category: reliability
package aiopspilot.postgresql.high_availability

import rego.v1

default deny := false

deny if {
  input.resource.type == "postgresql-server"
  input.resource.props.ha_mode != "ZoneRedundant"
}

deny_reason := "ha_not_zone_redundant" if deny
