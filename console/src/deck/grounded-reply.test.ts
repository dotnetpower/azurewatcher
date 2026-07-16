import { describe, expect, it } from "vitest";
import type { AnswerVerification } from "./backend";
import { verificationLabel } from "./grounded-reply";

function verification(authority: string): AnswerVerification {
  return {
    status: "consistent",
    authority,
    checks_completed: 1,
    checks_total: 1,
    evidence_refs: ["evidence-1"],
    reason_code: "screen_claims_supported",
    claims: [
      {
        claim_id: "c001",
        kind: "number",
        text: "24 events",
        span: { start: 0, end: 2 },
        raw_value: "24",
        normalized_value: "24",
        unit: null,
        anchors: ["events"],
        status: "supported",
        evidence_refs: ["evidence-1"],
        reason_code: null,
      },
    ],
  };
}

describe("verificationLabel", () => {
  it("names server evidence instead of the current screen", () => {
    expect(verificationLabel(verification("server_read_model"))).toBe(
      "Consistent with server evidence (1/1 claims supported)",
    );
  });

  it("keeps current-screen wording for browser snapshot evidence", () => {
    expect(verificationLabel(verification("client_snapshot"))).toBe(
      "Consistent with the current screen (1/1 claims supported)",
    );
  });
});
