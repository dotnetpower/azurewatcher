# METADATA
# title: Owner assignments at resource-group scope stay within a bounded count
# description: |
#   The number of principals holding the Owner role at resource-group scope MUST
#   stay at or below a bounded maximum. A proliferation of Owner grants dilutes
#   accountability and widens the privileged-access surface. The maximum is
#   tunable via input.parameters.max_owner_count (default 3). The T0 rule denies
#   when the Owner-assignment count exceeds the maximum.
# custom:
#   rule_id: resource-group.role-assignment.owner-count-within-limit
#   severity: medium
#   category: security
package fdai.resource_group.owner_count_within_limit

import rego.v1

default deny := false

max_owner_count := limit if {
	limit := input.parameters.max_owner_count
} else := 3

# Array comprehension (not a set) so identical Owner assignments each count once.
owner_count := count([1 |
	some assignment in input.resource.props.role_assignments
	assignment.role_name == "Owner"
])

deny if {
	input.resource.type == "resource-group"
	owner_count > max_owner_count
}

deny_reason := "resource_group_owner_count_exceeds_limit" if deny
