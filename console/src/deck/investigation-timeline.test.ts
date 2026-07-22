import { describe, expect, it } from "vitest";
import type { InvestigationActivity } from "./backend";
import { upsertInvestigationActivity } from "./investigation-timeline";

function activity(
  activityId: string,
  status: InvestigationActivity["status"],
): InvestigationActivity {
  return {
    activityId,
    kind: "health.querying",
    status,
    label: `Activity ${activityId}`,
    completed: status === "completed" ? 1 : 0,
    total: 1,
  };
}

describe("upsertInvestigationActivity", () => {
  it("appends new activities and updates an existing row in place", () => {
    const first = upsertInvestigationActivity([], activity("scope", "completed"));
    const second = upsertInvestigationActivity(first, activity("health", "running"));
    const completed = upsertInvestigationActivity(second, activity("health", "completed"));

    expect(completed.map((item) => item.activityId)).toEqual(["scope", "health"]);
    expect(completed[1]?.status).toBe("completed");
  });
});
