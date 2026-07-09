# METADATA
# title: Workload identity must not hold a privileged subscription-scoped role
# description: |
#   A workload (managed) identity MUST NOT be granted a privileged role
#   (Owner, Contributor, User Access Administrator, Role Based Access Control
#   Administrator) at subscription scope. Such a grant makes a single compromised
#   workload a subscription-wide blast radius. The T0 rule denies when the
#   inventory reports any subscription-scoped privileged role assignment on the
#   identity. Fail closed: an assignment whose scope or role is unknown is denied.
# custom:
#   rule_id: managed-identity.role-assignment.no-privileged-subscription-scope
#   severity: critical
#   category: security
package fdai.managed_identity.no_privileged_subscription_scope

import rego.v1

default deny := false

privileged_roles := {
	"Owner",
	"Contributor",
	"User Access Administrator",
	"Role Based Access Control Administrator",
}

deny if {
	input.resource.type == "managed-identity"
	some assignment in input.resource.props.role_assignments
	assignment.scope == "subscription"
	privileged_roles[assignment.role_name]
}

# Fail closed: an assignment missing a scope or role_name is treated as a violation.
deny if {
	input.resource.type == "managed-identity"
	some assignment in input.resource.props.role_assignments
	not assignment.scope
}

deny_reason := "workload_identity_privileged_at_subscription_scope" if deny
