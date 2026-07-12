import { describe, expect, it } from "vitest";
import type { AgentActivityMessage, AgentStatus } from "../hooks/use-agent-stream";
import {
  activeAgentCount,
  engagedGroups,
  isEngaged,
  makeInitialState,
  PANTHEON,
  reducer,
} from "./agents.model";

function stateMsg(
  agent: string,
  state: AgentStatus,
  correlation_id: string | null = null,
): AgentActivityMessage {
  return {
    type: "agent.state",
    agent,
    state,
    ts: "2026-07-12T00:00:00+00:00",
    correlation_id,
    detail: null,
  };
}

function ticketMsg(
  correlation_id: string,
  status: "open" | "investigating" | "resolved",
  rca: string | null = null,
): AgentActivityMessage {
  return {
    type: "incident.ticket",
    ticket_id: "FDAI-1",
    correlation_id,
    status,
    title: "t",
    severity: "high",
    involved_agents: ["Heimdall", "Forseti"],
    rca,
    ts: "2026-07-12T00:00:00+00:00",
  };
}

function turnMsg(correlation_id: string): AgentActivityMessage {
  return {
    type: "conversation.turn",
    correlation_id,
    from_agent: "Heimdall",
    to_agent: "Forseti",
    kind: "handoff",
    text: "anomaly 0.92",
    ts: "2026-07-12T00:00:00+00:00",
  };
}

describe("agents.model", () => {
  it("seeds all 15 agents idle", () => {
    const s = makeInitialState();
    expect(Object.keys(s.agents)).toHaveLength(15);
    expect(PANTHEON.every((a) => s.agents[a.name]?.state === "idle")).toBe(true);
  });

  it("applies an agent.state transition", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-1") });
    expect(s.agents.Heimdall?.state).toBe("collecting");
    expect(s.agents.Heimdall?.correlationId).toBe("inc-1");
  });

  it("opens then resolves an incident, preserving the rca", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    expect(s.incidentOrder).toEqual(["inc-1"]);
    expect(s.incidents["inc-1"]?.status).toBe("open");
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "investigating", "root cause X") });
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "resolved", "root cause X") });
    expect(s.incidents["inc-1"]?.status).toBe("resolved");
    expect(s.incidents["inc-1"]?.rca).toBe("root cause X");
    // Still a single incident (upsert, not duplicate).
    expect(s.incidentOrder).toEqual(["inc-1"]);
  });

  it("accumulates conversation turns on an incident", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });
    expect(s.incidents["inc-1"]?.turns).toHaveLength(2);
  });

  it("seeds a stub incident when a turn arrives before its ticket", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: turnMsg("inc-9") });
    expect(s.incidents["inc-9"]?.turns).toHaveLength(1);
    expect(s.incidentOrder).toEqual(["inc-9"]);
  });

  it("counts engaged (non-idle, non-watching) agents", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting") });
    s = reducer(s, { kind: "message", msg: stateMsg("Huginn", "watching") });
    s = reducer(s, { kind: "message", msg: stateMsg("Forseti", "analyzing") });
    expect(activeAgentCount(s)).toBe(2);
  });

  it("resets to the initial state", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "reset" });
    expect(s.incidentOrder).toHaveLength(0);
  });
});

describe("agents.model engagement helpers", () => {
  it("stores the streamed detail on the agent node", () => {
    let s = makeInitialState();
    s = reducer(s, {
      kind: "message",
      msg: {
        type: "agent.state",
        agent: "Forseti",
        state: "analyzing",
        ts: "2026-07-12T00:00:00+00:00",
        correlation_id: "inc-1",
        detail: "root-cause reasoning",
      },
    });
    expect(s.agents.Forseti?.detail).toBe("root-cause reasoning");
    expect(isEngaged(s.agents.Forseti!)).toBe(true);
    expect(isEngaged(s.agents.Odin!)).toBe(false);
  });

  it("groups engaged agents by the incident they work on", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-1") });
    s = reducer(s, { kind: "message", msg: stateMsg("Forseti", "analyzing", "inc-1") });
    // Watching / idle / correlation-less agents are excluded.
    s = reducer(s, { kind: "message", msg: stateMsg("Huginn", "watching", "inc-1") });
    s = reducer(s, { kind: "message", msg: stateMsg("Thor", "executing", null) });

    const groups = engagedGroups(s);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.correlationId).toBe("inc-1");
    expect(groups[0]?.agents).toEqual(["Forseti", "Heimdall"]); // sorted
    expect(groups[0]?.incident?.ticketId).toBe("FDAI-1");
  });

  it("returns one group per concurrent incident, newest first", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-old", "open") });
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-new", "open") });
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-old") });
    s = reducer(s, { kind: "message", msg: stateMsg("Thor", "executing", "inc-new") });

    const groups = engagedGroups(s);
    expect(groups.map((g) => g.correlationId)).toEqual(["inc-new", "inc-old"]);
  });

  it("returns no groups when the pantheon is at rest", () => {
    const s = makeInitialState();
    expect(engagedGroups(s)).toEqual([]);
  });
});
