import { describe, expect, test } from "vitest";
import {
  decodeAuditPage,
  decodeDashboardKpi,
  decodeHilQueuePage,
  decodeIncidentPage,
  decodeRcaView,
  ReadApiError,
} from "./api";

describe("read API response decoders", () => {
  test("reject malformed always-on payloads with a uniform contract error", () => {
    for (const decode of [decodeAuditPage, decodeDashboardKpi, decodeHilQueuePage, decodeIncidentPage]) {
      expect(() => decode({})).toThrow(ReadApiError);
      try { decode({}); } catch (error) {
        expect((error as ReadApiError).status).toBe(502);
      }
    }
  });

  test("decodes empty audit and HIL pages", () => {
    expect(decodeAuditPage({ items: [], next_cursor: null })).toEqual({ items: [], next_cursor: null });
    expect(decodeHilQueuePage({ items: [], total: 0 })).toEqual({ items: [], total: 0 });
  });

  test("decodes an incident page and rejects invalid status", () => {
    const item = {
      correlation_id: "corr-1",
      incident_id: null,
      ticket_id: null,
      title: "Rule example.rule",
      severity: "high",
      status: "in_progress",
      status_source: "audit_projection",
      disposition: "awaiting_hil",
      verdict: "hil",
      vertical: "change_safety",
      opened_at: "2026-07-14T10:00:00Z",
      last_updated_at: "2026-07-14T10:01:00Z",
      latest_mode: "shadow",
      history_count: 2,
    };
    expect(decodeIncidentPage({ items: [item], next_cursor: null }).items[0]?.status)
      .toBe("in_progress");
    expect(() => decodeIncidentPage({
      items: [{ ...item, status: "closed" }],
      next_cursor: null,
    })).toThrow(/status MUST/);
  });

  test("decodes an RCA view and rejects an invalid tier", () => {
    const grounded = {
      correlation_id: "corr-1",
      incident_id: null,
      hypotheses: [
        {
          seq: 2,
          tier: "t0",
          outcome: "grounded",
          grounded: true,
          cause: "public access open",
          confidence: 0.9,
          reason: "matched control",
          citations: [{ kind: "rule", ref: "storage.public-access" }],
          remediation_ref: "storage.disable-public-access",
          mode: "shadow",
          recorded_at: "2026-07-14T10:02:00Z",
        },
      ],
      response: {
        verdict: "auto",
        decision: "auto",
        action_kind: "risk_gate.shadow_authority",
        mode: "enforce",
        rollback_reference: "pr-7",
        recorded_at: "2026-07-14T10:03:00Z",
      },
    };
    const view = decodeRcaView(grounded);
    expect(view.hypotheses[0]?.grounded).toBe(true);
    expect(view.response?.verdict).toBe("auto");
    expect(() =>
      decodeRcaView({
        ...grounded,
        hypotheses: [{ ...grounded.hypotheses[0], tier: "t9" }],
      }),
    ).toThrow(/tier MUST/);
  });

  test("decodes an RCA view with an abstained hypothesis and null response", () => {
    const view = decodeRcaView({
      correlation_id: "corr-abstain",
      incident_id: null,
      hypotheses: [
        {
          seq: 1,
          tier: "t2",
          outcome: "abstained",
          grounded: false,
          cause: null,
          confidence: null,
          reason: "insufficient grounding",
          citations: [],
          remediation_ref: null,
          mode: "shadow",
          recorded_at: "2026-07-14T10:00:00Z",
        },
      ],
      response: null,
    });
    expect(view.hypotheses[0]?.grounded).toBe(false);
    expect(view.hypotheses[0]?.confidence).toBeNull();
    expect(view.response).toBeNull();
  });

  test("rejects non-finite KPI counters", () => {
    expect(() => decodeDashboardKpi({
      event_count: 1,
      shadow_share: Number.NaN,
      enforce_share: 0,
      hil_pending: 0,
      by_action_kind: {},
      by_outcome: {},
      by_tier: {},
      last_recorded_at: null,
    })).toThrow(/finite number/);
  });

  test("rejects semantically invalid KPI counters and shares", () => {
    const valid = {
      event_count: 1,
      shadow_share: 1,
      enforce_share: 0,
      hil_pending: 0,
      by_action_kind: {},
      by_outcome: {},
      by_tier: {},
      last_recorded_at: null,
    };
    expect(() => decodeDashboardKpi({ ...valid, event_count: -1 })).toThrow(/non-negative integer/);
    expect(() => decodeDashboardKpi({ ...valid, hil_pending: 0.5 })).toThrow(/non-negative integer/);
    expect(() => decodeDashboardKpi({ ...valid, shadow_share: 2 })).toThrow(/between 0 and 1/);
  });
});