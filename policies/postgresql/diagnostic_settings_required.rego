# METADATA
# title: Require diagnostic-settings on postgresql-server
# description: |
#   A postgresql-server MUST route log-plane events to a log-workspace.
# custom:
#   rule_id: postgresql-server.diagnostic-settings-required
#   severity: medium
#   category: reliability
package aiopspilot.postgresql.diagnostic_settings_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "postgresql-server"
  count(input.resource.props.diagnostic_settings) == 0
}

deny_reason := "no_diagnostic_settings" if deny
