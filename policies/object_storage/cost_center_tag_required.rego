# METADATA
# title: Cost-center tag required on object-storage
# description: |
#   Every object-storage account MUST carry a `cost_center` tag so
#   spend is attributable.
# custom:
#   rule_id: object-storage.cost-center-tag.required
#   severity: low
#   category: config_drift
package fdai.object_storage.cost_center_tag_required

import rego.v1

default deny := false

required_tag := t if {
  t := input.parameters.tag_name
} else := "cost_center"

deny if {
  input.resource.type == "object-storage"
  not input.resource.props.tags[required_tag]
}

deny_reason := sprintf("missing_required_tag:%s", [required_tag]) if deny
