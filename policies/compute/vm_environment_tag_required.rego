# METADATA
# title: Environment tag required on compute.vm
# description: |
#   Every compute.vm MUST carry an `environment` tag so lifecycle
#   policies apply predictably.
# custom:
#   rule_id: compute.vm.environment-tag.required
#   severity: low
#   category: config_drift
package aiopspilot.compute.vm_environment_tag_required

import rego.v1

default deny := false

required_tag := t if {
  t := input.parameters.tag_name
} else := "environment"

deny if {
  input.resource.type == "compute.vm"
  not input.resource.props.tags[required_tag]
}

deny_reason := sprintf("missing_required_tag:%s", [required_tag]) if deny
