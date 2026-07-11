# METADATA
# title: Publish resource change summary
# description: |
#   Reference example of a business-process rule. Fires when an
#   operator (or a scheduled tick emitted by a fork-side cron) submits
#   a `resource-group`-scoped event carrying the
#   ``props.request_kind == "change-summary"`` marker. The T0 verdict
#   is deterministic: the rule matches whenever the marker is present,
#   and the paired ActionType `ops.publish-change-summary` produces
#   the rendered Markdown report from the audit log.
#
#   This rule does NOT fire on ordinary resource-group inventory events -
#   the marker gate keeps the rule silent on the general event stream.
#   See `docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md` for the full
#   ontology walkthrough (ObjectType `ChangeSummary`, LinkType
#   `summarizes`).
# custom:
#   rule_id: ops.change-summary
#   severity: low
#   category: config_drift
package fdai.change_summary.publish_change_summary

import rego.v1

default deny := false

deny if {
	input.resource.type == "resource-group"
	input.resource.props.request_kind == "change-summary"
}

deny_reason := "change_summary_requested" if deny
