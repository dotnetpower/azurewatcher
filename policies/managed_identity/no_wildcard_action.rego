# METADATA
# title: Workload identity role must not grant wildcard actions
# description: |
#   A workload (managed) identity MUST NOT be granted a role whose action set
#   includes the wildcard "*" (all actions) or a wildcard data action. Wildcard
#   grants defeat least privilege and hide the true permission surface. The T0
#   rule denies when any assignment on the identity carries a wildcard action.
# custom:
#   rule_id: managed-identity.role-assignment.no-wildcard-action
#   severity: high
#   category: security
package fdai.managed_identity.no_wildcard_action

import rego.v1

default deny := false

deny if {
	input.resource.type == "managed-identity"
	some assignment in input.resource.props.role_assignments
	some action in assignment.actions
	action == "*"
}

deny if {
	input.resource.type == "managed-identity"
	some assignment in input.resource.props.role_assignments
	some action in assignment.data_actions
	action == "*"
}

deny_reason := "workload_identity_role_grants_wildcard_action" if deny
