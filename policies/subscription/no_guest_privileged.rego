# METADATA
# title: No guest principal holds a privileged role at subscription scope
# description: |
#   An external (guest) principal MUST NOT hold a privileged role (Owner,
#   Contributor, User Access Administrator, Role Based Access Control
#   Administrator) at subscription scope. Guest identities live outside the
#   tenant's lifecycle controls, so a standing privileged guest grant is a
#   durable escalation path. The T0 rule denies when the inventory reports a
#   guest principal with a subscription-scoped privileged assignment.
# custom:
#   rule_id: subscription.role-assignment.no-guest-privileged
#   severity: critical
#   category: security
package fdai.subscription.no_guest_privileged

import rego.v1

default deny := false

privileged_roles := {
	"Owner",
	"Contributor",
	"User Access Administrator",
	"Role Based Access Control Administrator",
}

deny if {
	input.resource.type == "subscription"
	some assignment in input.resource.props.role_assignments
	assignment.principal_type == "Guest"
	privileged_roles[assignment.role_name]
}

deny_reason := "guest_principal_privileged_at_subscription_scope" if deny
