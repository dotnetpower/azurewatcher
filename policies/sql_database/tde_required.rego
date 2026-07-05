# METADATA
# title: Transparent Data Encryption required on SQL database
# description: |
#   A `sql-database` MUST have TDE enabled. The T0 engine passes the
#   observed `tde_enabled` property; the rule denies whenever the
#   property is explicitly false (an unknown property abstains and
#   escalates to HIL rather than assuming compliance).
# custom:
#   rule_id: sql-database.tde-required
#   severity: high
#   category: security
package aiopspilot.sql_database.tde_required

import rego.v1

default deny := false

deny if {
	input.resource.type == "sql-database"
	input.resource.props.tde_enabled == false
}

deny_reason := "tde_disabled" if deny
