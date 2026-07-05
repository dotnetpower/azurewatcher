# METADATA
# title: Owner tag required on object-storage
# description: |
#   Every object-storage MUST carry a `owner` tag (or an operator-
#   overridden alternative name via `parameters.tag_name`) so that
#   ownership is auditable and the tag-add remediation is safe.
# custom:
#   rule_id: object-storage.owner-tag.required
#   severity: low
#   category: config_drift
package aiopspilot.object_storage.owner_tag_required

import rego.v1

default deny := false

required_tag := tag if {
	tag := input.parameters.tag_name
} else := "owner"

deny if {
	input.resource.type == "object-storage"
	not input.resource.props.tags[required_tag]
}

deny_reason := sprintf("missing_required_tag:%s", [required_tag]) if deny
