---
title: Agents and self-healing
description: How FDAI's fixed organization of agents watches your cloud, collaborates to resolve failures, and keeps you at the approve-or-reject level.
sidebar:
  order: 5
---

# Agents and self-healing

FDAI runs as a fixed **organization of 15 named agents**. Each agent has one
mandate, owns a set of object and action types, and communicates on a
schema-checked event bus. The org chart is the safety model: the agent that
judges is never the agent that executes, and the agent that executes never holds
your approval. When a resource drifts or a failure occurs, the agents
collaborate to resolve it - autonomously for the safe majority, and with your
approval for the risky few.

This page explains who the agents are, how they separate duties, how you operate
at the approve-or-reject level, and how they self-heal a failure end to end.

## The organization

The pantheon is defined once upstream and never changed by a fork. Odin plans,
Forseti judges, Thor executes, and staff agents govern the catalog and memory.

```mermaid
graph TD
  Odin["Odin - Master Planner"]
  Odin --> Thor["Thor - Responder / Executor"]
  Odin --> Forseti["Forseti - Judge"]
  Odin -. staff .-> Mimir["Mimir - Rule Steward"]
  Odin -. staff .-> Saga["Saga - Auditor"]
  Odin -. staff .-> Norns["Norns - Learner"]
  Odin -. staff .-> Muninn["Muninn - Memory"]
  Thor --> Vidar["Vidar - Recovery"]
  Thor --> Var["Var - Approver"]
  Thor --> Bragi["Bragi - Narrator"]
  Forseti --> Huginn["Huginn - Event Collector"]
  Forseti --> Heimdall["Heimdall - Observer"]
  Forseti --> Njord["Njord - Cost"]
  Forseti --> Freyr["Freyr - Capacity"]
  Forseti --> Loki["Loki - Chaos"]
```

| Agent | Role | In one line |
|-------|------|-------------|
| Odin | Master Planner | Arbitrates cross-vertical conflicts; final tie-breaker |
| Forseti | Judge | Issues the verdict (auto / HIL / deny); never executes |
| Thor | Responder | Dispatches verdicts; the sole privileged executor |
| Var | Approver | Carries the human HIL approval; distinct from Thor |
| Vidar | Recovery | Owns rollback and DR failover |
| Huginn | Event Collector | Ingests and correlates raw events |
| Heimdall | Observer | Watches drift and resource change |
| Njord / Freyr / Loki | Specialists | Advise on cost, capacity, chaos - they never execute |
| Mimir / Norns / Muninn | Governance staff | Rule stewardship, learning, memory |
| Saga | Auditor | Writes the append-only audit log |
| Bragi | Narrator | Translates your questions to and from the pipeline |

## Separation of duties

The safety guarantees come from who is *not* allowed to do what:

- **Judge is not executor.** Forseti decides; Thor acts. No agent both judges
  and executes, so a bad judgment cannot self-approve into a change.
- **Approval is a separate principal.** Var carries your approval; Thor cannot
  approve on your behalf.
- **Specialists advise, they do not act.** Njord, Freyr, and Loki feed
  judgment; they never reach the executor directly.
- **Two ports, no bypass.** Every agent has a typed pub/sub port (machine
  traffic) and a conversational port (your questions). A conversational request
  that asks for an action must re-enter the typed pipeline - the narrator can
  never execute directly.

## You operate at approve-or-reject

You do not drive the agents task by task. The organization runs the loop and
brings you decisions:

- The **safe majority auto-resolves** with a stop-condition, rollback path,
  blast-radius limit, and audit entry - no human in the path.
- The **risky few pause for you.** A HIL card reaches you through the channel
  you already use (Teams or Slack), and you approve or reject. Rejection and
  timeout are no-ops, and both are audited.
- You can **ask questions** in natural language through Bragi ("why did this
  fail over?") and get a grounded answer, without ever holding the executor's
  privileged identity.

Full walkthrough: [../guides/approve-change.md](../guides/approve-change.md).

## How a failure self-heals

When a resource degrades, the agents collaborate through the same pipeline that
handles every event. Here is one failover, end to end:

```mermaid
graph LR
  Huginn["Huginn<br/>collects signals"] --> Heimdall["Heimdall<br/>correlates drift"]
  Heimdall --> Forseti["Forseti<br/>judges verdict"]
  Njord -. advises .-> Forseti
  Freyr -. advises .-> Forseti
  Forseti -->|auto| Thor["Thor<br/>executes"]
  Forseti -->|hil| Var["Var<br/>your approval"]
  Var --> Thor
  Thor --> Vidar["Vidar<br/>rollback / failover"]
  Vidar --> Saga["Saga<br/>audits"]
  Thor --> Saga
  Saga -. signals .-> Norns["Norns<br/>learns"]
```

1. **Sense.** Huginn ingests the failure signals; Heimdall correlates them into
   one incident rather than a storm of alerts.
2. **Judge.** Forseti scores the incident, consults the specialists for cost and
   capacity trade-offs, and issues a verdict: auto, HIL, or deny.
3. **Act.** Thor dispatches. Low-risk recovery runs autonomously; a high-risk
   failover pauses for Var to carry your approval.
4. **Recover.** Vidar owns the rollback or DR failover, bounded by the action's
   stop-conditions and blast-radius.
5. **Record and learn.** Saga writes the audit entry; Norns turns recurring
   patterns into proposed catalog updates so the next occurrence resolves
   deterministically.

When specialists disagree on the same resource - Njord wants `scale_down` for
cost while Freyr wants `scale_up` for capacity - Odin arbitrates before Forseti
finalizes, so conflicting objectives never race to the executor.

## Next steps

| To learn about | Read |
|----------------|------|
| How every action inherits its safety contract | [ontology-driven-automation.md](ontology-driven-automation.md) |
| How verdicts become auto vs HIL | [risk-tiers.md](risk-tiers.md) |
| Approving or rejecting a queued change | [../guides/approve-change.md](../guides/approve-change.md) |
| Tracing a decision through the audit log | [../guides/read-audit-log.md](../guides/read-audit-log.md) |
| The full pantheon design | [../../roadmap/agent-pantheon.md](../../roadmap/agent-pantheon.md) |
