# METADATA
# title: Require HTTPS-only traffic on object-storage
# description: |
#   An object-storage account MUST reject HTTP; plaintext traffic to
#   the account is a data-in-transit exposure.
# custom:
#   rule_id: object-storage.https-only.required
#   severity: high
#   category: security
package fdai.object_storage.https_only_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "object-storage"
  input.resource.props.enable_https_traffic_only != true
}

deny_reason := "https_only_disabled" if deny
