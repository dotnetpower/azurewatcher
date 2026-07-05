# METADATA
# title: Disallow public network access on secret-store
# description: |
#   A secret-store MUST NOT accept traffic from the public internet;
#   the vault should be reachable only through private-endpoints or
#   the platform trusted-services bypass.
# custom:
#   rule_id: secret-store.public-network-access.disabled
#   severity: high
#   category: security
package aiopspilot.secret_store.public_network_access_disabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "secret-store"
  input.resource.props.public_network_access_enabled == true
}

deny_reason := "public_network_access_enabled" if deny
