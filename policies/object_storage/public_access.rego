# METADATA
# title: Deny public access on object-storage
# description: |
#   An object-storage bucket MUST NOT allow unauthenticated public
#   access. The T0 engine passes the resource props observed from the
#   inventory adapter; a violation is emitted whenever the
#   `public_access` property is enabled.
# custom:
#   rule_id: object-storage.public-access.deny
#   severity: high
#   category: security
package fdai.object_storage.public_access

import rego.v1

default deny := false

deny if {
	input.resource.type == "object-storage"
	input.resource.props.public_access == "enabled"
}

deny_reason := "public_access_enabled" if deny
