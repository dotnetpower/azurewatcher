# METADATA
# title: Environment tag required on resource-group
# description: |
#   Every resource-group MUST carry an `environment` tag so
#   lifecycle-scoped policies can key off it.
# custom:
#   rule_id: resource-group.environment-tag.required
#   severity: low
#   category: config_drift
package aiopspilot.resource_group.environment_tag_required

import rego.v1

default deny := false

required_tag := t if {
  t := input.parameters.tag_name
} else := "environment"

deny if {
  input.resource.type == "resource-group"
  not input.resource.props.tags[required_tag]
}

deny_reason := sprintf("missing_required_tag:%s", [required_tag]) if deny
