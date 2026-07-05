# METADATA
# title: Require diagnostic-settings on object-storage
# description: |
#   An object-storage account MUST route storage/blob logs to a
#   log-workspace for auditability.
# custom:
#   rule_id: object-storage.diagnostic-settings-required
#   severity: medium
#   category: reliability
package aiopspilot.object_storage.diagnostic_settings_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  count(input.resource.props.diagnostic_settings) == 0
}

deny_reason := "no_diagnostic_settings" if deny
