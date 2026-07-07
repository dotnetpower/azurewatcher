# METADATA
# title: Require adequate PITR window on postgresql-server
# description: |
#   A postgresql-server MUST retain at least the operator-configured
#   number of days of backups (default 7) to support point-in-time
#   restore after an accidental data change.
# custom:
#   rule_id: postgresql-server.point-in-time-restore
#   severity: high
#   category: reliability
package fdai.postgresql.point_in_time_restore

import rego.v1

default deny := false

min_days := d if {
  d := input.parameters.min_retention_days
} else := 7

deny if {
  input.resource.type == "postgresql-server"
  input.resource.props.backup_retention_days < min_days
}

deny_reason := "backup_retention_below_min" if deny
