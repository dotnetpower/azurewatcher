# UI CLI - operator-console streaming-briefing mock

A static, dependency-free mock of the AIOpsPilot **operator-console CLI**, rendered as a
terminal that plays a JARVIS-style *streaming briefing*: boot banner, a narrated greeting,
a throughput chart drawn left-to-right, trust-tier bars filling, then a branch into either
the human-in-the-loop (**HIL**) approval cards or an all-clear free-chat prompt.

> This is a design mock (plain HTML/CSS/JS, no build, no backend). It is English-only and
> customer-agnostic; every value shown is synthetic. It is **not** the production console -
> the real surface is planned as an Ink (React for CLI) app that talks to the headless core
> over read-only `console-tool` calls. See
> [../../.github/instructions/app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)
> (Operator console) and
> [../../.github/instructions/architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
> (Action ontology and console vocabulary).

## The idea: never a blank prompt

Coding CLIs (Copilot, Claude Code, Gemini) open on an empty cursor - a first-time user does
not know what to do. AIOpsPilot is the opposite: the control plane is **already running your
cloud autonomously**, so the console is a **pull-direction** surface. It opens on a briefing
that answers "what happened, and what needs me?", never on a blank prompt.

- **Never blank** - opens on a standing briefing of what autonomy did.
- **Always a next verb** - every item carries an explicit action (approve / reject / review).
- **Deterministic-first UX** - free-form narrator chat is the fallback, not the front door.

## What it demonstrates

- **Streaming narration** - the `narrator` streams text token by token. It is a translator,
  never a judge: it only narrates real state and never fabricates numbers.
- **Streaming charts** - the event-throughput chart is drawn column by column, and the
  T0/T1/T2 tier bars fill frame by frame. Streaming is a presentation concern only.
- **Branch on state** - toggle **branch: HIL** vs **branch: calm**:
  - **HIL** - approval cards for items autonomy deferred to a human. Each card shows risk,
    why, tier basis, the four safety invariants (blast radius, stop-condition, rollback,
    audit), the PR-native path, and the gate (`you != actor`, breakglass + quorum for HIGH).
  - **calm** - nothing needs a signature, so it invites a read-only free-chat exchange.
- **side_effect_class tags** - `[read]`, `[simulate]`, `[approve]`, `[breakglass]` are shown
  on the tool/action lines, matching the console-tool tagging in the architecture doc.

## Controls

- **replay** - restart the briefing.
- **branch: HIL / calm** - switch between "items need you" and "all clear".
- **speed** - cycle playback speed (1x / 2x / 4x / 0.5x).

## Run

Open the page directly in a browser (no build step, no server):

```
mocks/ui-cli/index.html
```

## Files

| File | Purpose |
|------|---------|
| [index.html](index.html) | terminal chrome, palette, layout, controls |
| [app.js](app.js) | synthetic briefing data + streaming/animation runtime + phase orchestration |

## Palette

Dark terminal aligned with the "Calm Slate" UI kit ([../ui](../ui/README.md)) so the CLI and
the web console read as one product. Muted accents carry meaning, never decoration:

| Role | Hex |
|------|-----|
| Background / panel | `#0E1216` / `#121A21` |
| Text / dim | `#C7CDD2` / `#7C848B` |
| T0 teal / T1 steel / T2 plum | `#63A69C` / `#6E9BCB` / `#A896CE` |
| LOW sage / MEDIUM terracotta / HIGH dusty red | `#7FB077` / `#D6925F` / `#D07A7A` |

## Conventions

- English-only content and identifiers; no customer names, ids, endpoints, or secrets.
- The console is read-only. Approvals are PR-native (approve = open a PR; reject = no-op +
  audit); nothing here executes a privileged call. Self-approval is blocked (`you != actor`).
- Design mock only - not wired to the core, not part of the shipped console.
