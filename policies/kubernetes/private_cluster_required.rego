# METADATA
# title: Require private API server on kubernetes-cluster
# description: |
#   A kubernetes-cluster serving workloads MUST have the API server
#   reachable only through a private endpoint.
# custom:
#   rule_id: kubernetes-cluster.private-cluster
#   severity: high
#   category: security
package aiopspilot.kubernetes.private_cluster_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "kubernetes-cluster"
  input.resource.props.private_cluster_enabled != true
}

deny_reason := "api_server_public" if deny
