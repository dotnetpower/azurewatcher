# METADATA
# title: Require diagnostic-settings on sql-database
# description: |
#   A sql-database MUST route audit and metric logs to a
#   log-workspace.
# custom:
#   rule_id: sql-database.diagnostic-settings-required
#   severity: medium
#   category: reliability
package aiopspilot.sql_database.diagnostic_settings_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "sql-database"
  count(input.resource.props.diagnostic_settings) == 0
}

deny_reason := "no_diagnostic_settings" if deny
