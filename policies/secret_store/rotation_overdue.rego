# METADATA
# title: Secret rotation overdue
# description: |
#   Any secret whose age exceeds the operator-supplied
#   `parameters.max_age_days` (default 90) MUST be rotated. The T0
#   engine passes the observed secret metadata; a violation triggers
#   the `remediate.rotate-secret` action (subject to the risk-gate).
# custom:
#   rule_id: secret-store.rotation-overdue
#   severity: high
#   category: security
package aiopspilot.secret_store.rotation_overdue

import rego.v1

default deny := false

max_age := m if {
	m := input.parameters.max_age_days
} else := 90

deny if {
	input.resource.type == "secret-store"
	input.resource.props.age_days > max_age
}

deny_reason := "secret_age_over_threshold" if deny
