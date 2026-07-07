# METADATA
# title: Require diagnostic-settings on secret-store
# description: |
#   A secret-store MUST route AuditEvent logs to a log-workspace so
#   every secret read/write is auditable.
# custom:
#   rule_id: secret-store.diagnostic-settings-required
#   severity: high
#   category: security
package fdai.secret_store.diagnostic_settings_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "secret-store"
  count(input.resource.props.diagnostic_settings) == 0
}

deny_reason := "no_diagnostic_settings" if deny
