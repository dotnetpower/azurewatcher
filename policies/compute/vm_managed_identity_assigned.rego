# METADATA
# title: Require a managed-identity on compute.vm
# description: |
#   A compute.vm MUST have a system- or user-assigned managed-identity
#   so it does not depend on secrets embedded in application settings.
# custom:
#   rule_id: compute.vm.managed-identity.assigned
#   severity: medium
#   category: security
package fdai.compute.vm_managed_identity_assigned

import rego.v1

default deny := false

deny if {
  input.resource.type == "compute.vm"
  input.resource.props.identity_type == "None"
}

deny_reason := "no_managed_identity" if deny
