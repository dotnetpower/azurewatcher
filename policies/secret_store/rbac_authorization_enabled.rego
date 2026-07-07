# METADATA
# title: Require RBAC authorization on secret-store
# description: |
#   A secret-store MUST use RBAC authorization; legacy access-policies
#   leave stale key-based grants un-audited. The T0 rule denies when the
#   inventory reports RBAC as disabled.
# custom:
#   rule_id: secret-store.rbac-authorization.enabled
#   severity: high
#   category: security
package fdai.secret_store.rbac_authorization_enabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "secret-store"
  input.resource.props.rbac_authorization_enabled != true
}

deny_reason := "rbac_authorization_disabled" if deny
