# `rule-catalog/sources/`

Per-source rule snapshots (one directory per upstream source: WAF, CIS, OPA, IaC scanners, kube-bench, ...).
Each file carries `provenance` (source URL + resolved revision + content hash + license + redistribution flag).

- [`registry.yaml`](registry.yaml) - canonical list of sources the seed
  catalog draws from, with URL prefixes, licenses, and redistribution
  posture. Referenced by [`../RULE_AUTHORING_GUIDE.md`](../RULE_AUTHORING_GUIDE.md)
  when picking the `source` enum value on a new rule.
