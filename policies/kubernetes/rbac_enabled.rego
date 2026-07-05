# METADATA
# title: Require Azure RBAC on kubernetes-cluster
# description: |
#   A kubernetes-cluster MUST use Azure RBAC integration; kubectl
#   permissions MUST NOT rely on the built-in local admin.
# custom:
#   rule_id: kubernetes-cluster.rbac-enabled
#   severity: high
#   category: security
package aiopspilot.kubernetes.rbac_enabled

import rego.v1

default deny := false

deny if {
  input.resource.type == "kubernetes-cluster"
  input.resource.props.azure_rbac_enabled != true
}

deny_reason := "azure_rbac_disabled" if deny
