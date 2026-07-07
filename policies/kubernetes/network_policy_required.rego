# METADATA
# title: Require a network policy engine on kubernetes-cluster
# description: |
#   A kubernetes-cluster MUST run a network-policy engine (calico or
#   azure) so pod-to-pod traffic can be restricted.
# custom:
#   rule_id: kubernetes-cluster.network-policy
#   severity: high
#   category: security
package fdai.kubernetes.network_policy_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "kubernetes-cluster"
  not input.resource.props.network_policy
}

deny_reason := "no_network_policy" if deny
