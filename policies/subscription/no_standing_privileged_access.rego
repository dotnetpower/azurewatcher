# METADATA
# title: Privileged subscription-scoped access must be just-in-time, not standing
# description: |
#   A privileged role (Owner, Contributor, User Access Administrator, Role Based
#   Access Control Administrator) at subscription scope MUST be granted as
#   just-in-time eligible access (PIM-style), not as a permanent standing
#   assignment. Standing privileged access widens the always-on attack surface.
#   The T0 rule denies when a privileged subscription-scoped assignment is marked
#   standing (permanent). Fail closed: an assignment missing the standing flag is
#   treated as standing.
# custom:
#   rule_id: subscription.role-assignment.no-standing-privileged-access
#   severity: high
#   category: security
package fdai.subscription.no_standing_privileged_access

import rego.v1

default deny := false

privileged_roles := {
	"Owner",
	"Contributor",
	"User Access Administrator",
	"Role Based Access Control Administrator",
}

# The standing flag is present (explicitly true or false).
has_standing_flag(assignment) if assignment.standing == true

has_standing_flag(assignment) if assignment.standing == false

is_standing(assignment) if assignment.standing == true

# Fail closed: absence of an explicit eligible/just-in-time marker is standing.
is_standing(assignment) if not has_standing_flag(assignment)

deny if {
	input.resource.type == "subscription"
	some assignment in input.resource.props.role_assignments
	privileged_roles[assignment.role_name]
	is_standing(assignment)
}

deny_reason := "standing_privileged_subscription_access" if deny
