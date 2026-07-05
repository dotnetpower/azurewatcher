# METADATA
# title: Require geo-redundant backup on sql-database
# description: |
#   A sql-database that stores customer-facing data MUST use
#   geo-redundant backup storage so a regional outage does not lose
#   the point-in-time restore window.
# custom:
#   rule_id: sql-database.geo-redundant-backup
#   severity: high
#   category: reliability
package aiopspilot.sql_database.geo_redundant_backup

import rego.v1

default deny := false

deny if {
  input.resource.type == "sql-database"
  input.resource.props.geo_redundant_backup_enabled != true
}

deny_reason := "geo_redundant_backup_disabled" if deny
