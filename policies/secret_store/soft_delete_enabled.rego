# METADATA
# title: Require soft-delete on secret-store
# description: |
#   A secret-store MUST have soft-delete enabled so a purge is
#   recoverable within the provider retention window.
# custom:
#   rule_id: secret-store.soft-delete.enabled
#   severity: high
#   category: security
package aiopspilot.secret_store.soft_delete_enabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "secret-store"
  input.resource.props.soft_delete_enabled != true
}

deny_reason := "soft_delete_disabled" if deny
