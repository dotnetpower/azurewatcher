# METADATA
# title: Owner tag required on resource-group
# description: |
#   Every resource-group MUST carry an `owner` tag so ownership is
#   auditable.
# custom:
#   rule_id: resource-group.owner-tag.required
#   severity: low
#   category: config_drift
package fdai.resource_group.owner_tag_required

import rego.v1

default deny := false

required_tag := t if {
  t := input.parameters.tag_name
} else := "owner"

deny if {
  input.resource.type == "resource-group"
  not input.resource.props.tags[required_tag]
}

deny_reason := sprintf("missing_required_tag:%s", [required_tag]) if deny
