# METADATA
# title: Require purge protection on secret-store
# description: |
#   A secret-store MUST have purge protection enabled so a soft-deleted
#   secret cannot be purged during the retention window. Turning it on
#   is irreversible - the ActionType is HIL-gated until measured.
# custom:
#   rule_id: secret-store.purge-protection.enabled
#   severity: high
#   category: security
package fdai.secret_store.purge_protection_enabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "secret-store"
  input.resource.props.purge_protection_enabled != true
}

deny_reason := "purge_protection_disabled" if deny
