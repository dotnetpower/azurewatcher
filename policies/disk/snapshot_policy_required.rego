# METADATA
# title: Require a snapshot policy on disk
# description: |
#   A disk holding stateful data MUST be enrolled in a snapshot
#   policy so a rollback point exists.
# custom:
#   rule_id: disk.snapshot-policy.required
#   severity: medium
#   category: reliability
package fdai.disk.snapshot_policy_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "disk"
  input.resource.props.snapshot_policy_present != true
}

deny_reason := "no_snapshot_policy" if deny
