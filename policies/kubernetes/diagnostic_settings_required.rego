# METADATA
# title: Require diagnostic-settings on kubernetes-cluster
# description: |
#   A kubernetes-cluster MUST route audit and controller-manager
#   logs to a log-workspace.
# custom:
#   rule_id: kubernetes-cluster.diagnostic-settings-required
#   severity: medium
#   category: reliability
package aiopspilot.kubernetes.diagnostic_settings_required

import rego.v1

default deny := false

deny if {
  input.resource.type == "kubernetes-cluster"
  count(input.resource.props.diagnostic_settings) == 0
}

deny_reason := "no_diagnostic_settings" if deny
