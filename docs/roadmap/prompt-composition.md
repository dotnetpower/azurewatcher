---
title: Evolving System Prompt
---
# Evolving System Prompt

The T2 tier and quality gate consume a **composable, catalog-as-code prompt**
instead of a single hardcoded string. This document is the design source of
truth: how the layers assemble, where each artifact lives, which seams the
composition root wires, and how we measure that the model actually reads what
we sent. It expands the LLM contract in
[llm-strategy.md](llm-strategy.md#t2---reasoning-tier-quality-gate-required) and
the trust routing in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md).

> **Scope.** Upstream is generic and Azure-first. Web search and any
> customer-specific override arrive as fork-only bindings; the core repo ships
> deny-by-default fakes so a fork MUST opt in explicitly
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
>
> **Status.** Wave 1 has landed - the base prompt is externalized under
> `rule-catalog/prompts/` and the composition root loads it. Waves 2-5 (task
> packs, tools / web search, operator memory, debate orchestrator, measurement)
> are documented here but not yet implemented. Every wave promotes only after
> its shadow gate passes; see [Rollout waves](#rollout-waves).

## Design at a glance

Prompts are **data**, not literals in code. The composition root loads them
from `rule-catalog/prompts/` at startup, indexes them by capability, and hands
resolved bodies to the Azure OpenAI adapters. Runtime layers (rule-catalog
citations, operator-memory entries, tool outputs, web snippets, debate
transcripts) are wrapped in `trusted="false"` XML tags so the model treats
them as data. The **deterministic verifier remains the sole execution
authority** - every added role, tool, and layer produces material for that
verifier, never a shortcut around it.

## Role x layer matrix

Prompts have two axes. **Layers** are what content types compose an assembled
prompt; **roles** decide which base / pack / tool set applies. Wave 1 ships
only the reviewer role; the others are declared so future waves slot into a
stable seam.

| Layer \\ Role | Proposer | Critic | Judge |
|--------------|----------|--------|-------|
| Base (role skeleton) | `base/t2-proposer.vN.yaml` | `base/t2-critic.vN.yaml` | `base/t2-judge.vN.yaml` |
| Task Skill Pack | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (usually shared with proposer pack) |
| Tool Manifest | tools + optional `web.search` | tools (read-only) | none (Judge cannot call tools) |
| Domain Context (RAG) | rule / past-incident citations | same | same |
| Web Snippets | if Proposer fetched them | read-only | read-only |
| Operator Memory | scope-bounded | scope-bounded | scope-bounded |
| Debate Transcript | (empty on first turn) | Proposer output | Proposer + Critic outputs |

Today the reviewer role runs a two-model cross-check (Wave 2 keeps this). Wave
4 adds the Critic and Wave 4.5 promotes the loop to a Proposer / Critic / Judge
orchestrator; the matrix already reserves each cell so those additions do not
require a refactor.

## Layer catalog

Each layer has a fixed job and a fixed storage tier.

- **Base** - short, immutable role skeleton (output contract, verifier-as-authority
  reminder, JSON-only output rule). Wave 1 target: <= 128 tokens.
- **Task Skill Pack** - capability-scoped instructions (e.g. RCA grounding,
  action proposal, novelty classification). Each pack cites the rule-catalog
  entries a capability may reference.
- **Tool Manifest** - the subset of tools this role may call. Declaring them
  outside the base prompt keeps the base short and cache-friendly.
- **Domain Context (RAG)** - rule excerpts and prior-incident references
  selected per event. Never persisted alongside the prompt; the audit records
  the cited ids and vector-hit scores only.
- **Web Snippets** - fetched only under the [Web search policy](#web-search-policy).
  Wrapped in `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`.
- **Operator Memory** - scope-bounded, HIL-approved notes from operator
  feedback (HIL rejects, override justifications, ChatOps preferences, PR
  reviews). Never global; see [Operator memory pipeline](#operator-memory-pipeline).
- **Debate Transcript** - previous roles' outputs, threaded to later roles as
  read-only context.

## Storage

### Catalog-as-code (git-tracked)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # JSON Schema every artifact validates against
    base/
      t2-cross-check.v1.yaml      # Wave 1 (shipped)
      t2-proposer.vN.yaml         # Wave 3 (planned)
      t2-critic.vN.yaml           # Wave 4 (planned)
      t2-judge.vN.yaml            # Wave 4.5 (planned)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
    roles/                        # Wave 3+
```

### Runtime data (Postgres, hash-addressed blobs)

Two new tables land alongside the existing state / audit schema. They are
append-only and hash-addressable so replay never re-fetches external content.

```sql
CREATE TABLE operator_memory (
  id            uuid PRIMARY KEY,
  scope_kind    text NOT NULL,     -- 'resource-group' | 'resource' | 'vertical'
  scope_ref     text NOT NULL,
  category      text NOT NULL,
  body          text NOT NULL,     -- wrapped in <operator_note> at inject time
  source_event  text NOT NULL,     -- 'hil.reject' | 'override.create' | ...
  source_ref    text NOT NULL,     -- audit id / PR url / message id
  author        text NOT NULL,
  approved_by   text NOT NULL,     -- no self-approval
  created_at    timestamptz NOT NULL,
  superseded_by uuid,
  ttl           interval
);

CREATE TABLE agent_transcript (
  id             uuid PRIMARY KEY,
  event_id       text NOT NULL,
  round          smallint NOT NULL,
  role           text NOT NULL,    -- 'proposer' | 'critic' | 'judge'
  model_id       text NOT NULL,
  prompt_hash    text NOT NULL,
  layer_manifest jsonb NOT NULL,   -- ordered layer refs + version + token count
  tool_calls     jsonb NOT NULL,
  response_hash  text NOT NULL,
  cost_usd       numeric NOT NULL,
  latency_ms     integer NOT NULL,
  created_at     timestamptz NOT NULL
);

CREATE TABLE web_evidence (
  content_hash    text PRIMARY KEY,
  url             text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  intent          text NOT NULL,
  sanitized_text  text NOT NULL,
  injection_flags jsonb NOT NULL
);
```

Global-scope operator memory is rejected at write time - the row would be
too broad for the [Human Override](../../.github/instructions/architecture.instructions.md#human-override)
policy this inherits.

## Provider protocols (DI seams)

The core stays behind Protocols; the Azure adapter provides one implementation
per seam. New seams introduced by this design:

| Seam | Kind | Wave | Role |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (shipped) | Load / index prompt YAMLs |
| `PromptComposer` | async | 2 | Assemble Role x Layer per event |
| `ToolRegistry` | sync | 2.5 | Load tool YAML manifests |
| `ToolExecutor` | async | 2.5 | Dispatch model-issued tool calls |
| `OperatorMemoryStore` | async | 3 | Read / append scope-bounded notes |
| `WebSearchProvider` | async | 5 | Outbound HTTP behind allowlist |
| `EvidenceStore` | async | 5 | Persist hash-addressed web snapshots |
| `AgentTranscriptStore` | async | 4.5 | Append-only debate rows |
| `DebateOrchestrator` | async | 4.5 | Proposer -> Critic -> Judge loop |

I/O-bound seams follow the async-by-default rule for provider protocols
declared in
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety).

## Tool use subsystem

Tools are catalog-as-code, mirroring the rule catalog. Each YAML declares its
description, invocation schema, capability gate, allowlist, and output wrapper.

- **Allowlist per capability**: a capability's `llm-registry` entry names the
  tools its Proposer / Critic may call. This keeps the tool manifest short so
  the "lost in the middle" failure mode does not creep in.
- **Untrusted output**: every tool result is wrapped
  (`<tool_result trusted="false" tool="..." ...>...</tool_result>`) and treated
  as data. The verifier and policy re-check remain authoritative.
- **Budget**: each tool declares `cost_budget_usd_per_call` and the composer
  enforces a per-event ceiling; overrun aborts to HIL.
- **Judge holds no tools**: judgment is separation-of-duties; a Judge that
  calls tools would collapse into a second Proposer.

## Web search policy

Web search is the last-resort tool. It is opt-in per fork and never a
grounding source.

- **Default off**: upstream ships a no-op `WebSearchProvider`. A fork provides
  an API key and a curated domain allowlist to activate it.
- **When it may run**: T2 case, novelty score above threshold, capability's
  tool allowlist includes `web.search`, and the per-event query / cost budget
  is not exhausted.
- **Domain allowlist**: primary sources only (vendor docs, RFCs, NVD, CVE
  registries). Blogs, forums, and social media are prohibited.
- **Snippet handling**: HTML stripped; prompt-like patterns
  (`ignore previous`, `system:`, etc.) detected and flagged; content wrapped in
  `<web_snippet trusted="false">...</web_snippet>` before injection.
- **Not a grounding source**: `cited_rule_ids` MUST still resolve to
  rule-catalog entries. Useful web findings feed the rule-catalog discovery
  loop; they never satisfy the current event's grounding requirement.
- **Replay determinism**: results are stored by `(content_hash, url, fetched_at)`
  in `web_evidence`; audit entries reference the hash. Replay reads the
  stored snapshot instead of re-fetching, so past runs stay reproducible.

## Debate orchestrator (Proposer / Critic / Judge)

Debate runs only when the router asks for it - typically high-severity, high
novelty, or explicit operator-memory guidance. The default T2 path is still
the two-model cross-check documented in [llm-strategy.md](llm-strategy.md).

```text
Proposer  -- candidate + citations + confidence
   |
   v
Critic    -- objections: [{severity, cited_rule_id, alt_action?}]
   |
   v
Judge     -- decision in {accept, revise_and_retry (<=1), escalate_hil}
   |
   +--> accept       -> deterministic verifier -> risk gate
   +--> revise       -> Proposer 1 retry (total rounds <= 2)
   +--> escalate_hil -> stop
```

Hard limits per event: `debate.max_rounds <= 2`, `debate.max_wall_seconds`,
`debate.max_cost_usd`. Any overrun aborts to HIL. The Critic MUST be a
different-publisher model from the Proposer (extension of the mixed-model
distinctness rule in
[llm-strategy.md](llm-strategy.md#t2---reasoning-tier-quality-gate-required)).
The Judge may be a smaller / cheaper model.

Critic's role is not "another opinion"; it is a checklist against the four
safety invariants (stop-condition, rollback, blast-radius, audit-log) plus
citation validity and contradiction against operator memory.

## Operator memory pipeline

Operator feedback becomes memory in a two-step gate:

```text
HIL reject / approve reason ------\\
Override create / modify event   --+--> operator-memory candidate
ChatOps preference message       --|         |
PR review comment on rem PR      --/         v
                                     HIL second approval (no self-approval)
                                             |
                                             v
                                  operator_memory row (append-only)
```

- **Scope MUST be resource-group or narrower.** Broader scope becomes a rule
  change, not an override, and flows through the catalog pipeline.
- **Sanitize + wrap on inject**: memory bodies enter the prompt inside
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  tags, and the base prompt forbids following instructions inside those tags.
- **Discovery signal**: long-lived overrides or many similar memory rows for
  the same rule feed the rule-catalog discovery loop as candidate revisions or
  retirements.

## Recognition measurement

Long prompts silently drop instructions. We treat "the model actually reads
what we sent" as a first-class KPI, gated before promoting a prompt to enforce.

- **Hard token budget** - the composer estimates tokens per assembled prompt.
  Overrun aborts to HIL and increments `prompt.token_budget.exceeded_rate`.
  Lower-priority layers (oldest operator memory first) are dropped explicitly
  with an audit-visible reason.
- **Canary tokens** - the composer inserts tagged layer markers
  (`<layer id="pack.rca.v3">...</layer>`). Roles report which layers they
  acknowledged; unacknowledged high-priority layers surface as a defect.
- **Adherence rate** - JSON schema violations, missing required fields, and
  citation-rule-id validity are measured on a frozen scenario set every
  prompt-version bump.
- **Position sensitivity** - controlled fixtures place the same instruction at
  base vs. pack vs. end and compare adherence. Consistent dips at a position
  signal a base rewrite.
- **Mixed-model agreement rate** - existing quality-gate disagreement rate is
  tracked per prompt version so regressions surface immediately.
- **Debate economics** - `debate.rounds.p95`, `debate.cost_usd.p95`,
  `debate.timeout_to_hil_rate`, and `critic.reversal_rate` are tracked once
  the debate orchestrator lands.

Promotion gates (initial values, tuned per capability): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `debate.timeout_to_hil_rate
<= 5%`, `critic.reversal_rate in [1%, 15%]`.

## Safety invariants (extensions)

The eight invariants in
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety)
extend with six more as this design lands:

1. Web-search output is NEVER a `cited_rule_id`.
2. Tool results and web snippets are ALWAYS wrapped in `trusted="false"` XML.
3. Debate loops have hard `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   ceilings; any overrun aborts to HIL.
4. Critic and Proposer publishers MUST differ; a same-publisher pair collapses
   into a single voter.
5. Judge MUST NOT call tools; judgment and generation are separated.
6. Web evidence is hash-addressed immutable; replay reads snapshots, never
   re-fetches.

## Rollout waves

Every wave lands in shadow first; promotion requires the previous wave's
promotion gates to hold.

| Wave | Deliverable | Shipped |
|------|-------------|---------|
| 1 | Externalize base prompt to catalog + `PromptRegistry` + composition wiring | yes |
| 2 | Task packs + Recognition probe scaffold + KPI extension | planned |
| 2.5 | `ToolRegistry` + `ToolExecutor` for `rule.query` / `state.query` / `audit.query` (no web search) | planned |
| 3 | Operator Memory schema + HIL-second-approval pipeline (starts with HIL reject reason only) | planned |
| 4 | Critic role (2-role debate: Proposer + Critic, verifier still authoritative) | planned |
| 4.5 | Judge role and the full `DebateOrchestrator` with `max_rounds = 1` | planned |
| 5 | Web search opt-in for forks (no-op provider upstream; injection detection required for enforce) | planned |

## Wave 1 - what shipped

Wave 1 introduces the seam without changing runtime behavior.

- `rule-catalog/prompts/schema/prompt.schema.json` - JSON Schema for prompt
  artifacts.
- `rule-catalog/prompts/base/t2-cross-check.v1.yaml` - the extracted T2 base
  prompt.
- `src/aiopspilot/core/prompts/` - `PromptRegistry` Protocol,
  `FileSystemPromptRegistry` implementation, aggregate-error validation.
- `bind_azure_llm_bindings` accepts an optional `system_prompt` and threads it
  through every cross-check config.
- `__main__._finalize_llm_bindings` loads the base prompt via
  `FileSystemPromptRegistry` and passes it in.
- `tests/core/prompts/test_yaml_matches_dataclass_default.py` pins the shipped
  YAML body to the dataclass default so the two cannot drift during the
  transition. Wave 2 removes the default and deletes this pin.

## Related docs

| To learn about | Read |
|----------------|------|
| Tier boundaries and quality gate | [llm-strategy.md](llm-strategy.md) |
| Trust routing and control loop | [../../.github/instructions/architecture.instructions.md](../../.github/instructions/architecture.instructions.md) |
| Human override policy this design extends | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| Safety invariants and coding conventions | [../../.github/instructions/coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection threat model | [security-and-identity.md](security-and-identity.md) |
| Rule catalog and provenance rule | [rule-catalog-collection.md](rule-catalog-collection.md) |
