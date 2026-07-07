# `rule-catalog/`

Rule catalog (catalog-as-code) - normalized, versioned rule data.

Data-only YAML tree. Pipeline code lives in
[src/fdai/rule_catalog/](../src/fdai/rule_catalog/README.md).
Full design: [docs/roadmap/rule-catalog-collection.md](../docs/roadmap/rule-catalog-collection.md).

- [`RULE_AUTHORING_GUIDE.md`](RULE_AUTHORING_GUIDE.md) - canonical
  procedure to author a new rule (hand-authored, generated, or
  LLM-proposed).
- [`sources/registry.yaml`](sources/registry.yaml) - normative sources
  the seed catalog draws from and their license / redistribution posture.
