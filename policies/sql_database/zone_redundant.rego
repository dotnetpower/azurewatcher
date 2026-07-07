# METADATA
# title: Require zone-redundant sql-database
# description: |
#   A sql-database MUST run in a zone-redundant configuration.
# custom:
#   rule_id: sql-database.zone-redundant
#   severity: high
#   category: reliability
package fdai.sql_database.zone_redundant

import rego.v1

default deny := false

deny if {
  input.resource.type == "sql-database"
  input.resource.props.zone_redundant != true
}

deny_reason := "sql_not_zone_redundant" if deny
