# METADATA
# title: Require a private-endpoint on object-storage
# description: |
#   An object-storage account holding data MUST be reachable only
#   through a private-endpoint; public network access is denied.
# custom:
#   rule_id: object-storage.private-endpoint.required
#   severity: high
#   category: security
package fdai.object_storage.private_endpoint_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.public_network_access_enabled == true
}

deny if {
  input.resource.type == "object-storage"
  count(input.resource.props.private_endpoints) == 0
}

deny_reason := "no_private_endpoint" if deny
