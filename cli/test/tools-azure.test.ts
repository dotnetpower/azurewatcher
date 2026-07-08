/**
 * Contract tests for the UI-agnostic Azure data tools (inventory, metrics, cost,
 * quota, activity log). These lock the parsing/error/read-only contracts so the
 * data layer stays correct as the UI (CLI cockpit, web console, etc.) changes.
 * The Azure token and HTTP are mocked - no network, no `az`, no credentials.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the shared token module so no `az` / credentials are needed. The
// subscription placeholder is the all-zero id allowed by the GUID gate.
vi.mock("../src/narrator/azure-token.js", () => ({
  MGMT_RESOURCE: "https://management.azure.com",
  azToken: async () => "test-token",
  azSubscriptionId: async () => "00000000-0000-0000-0000-000000000000",
}));

import { queryInventory } from "../src/narrator/inventory.js";
import { getMetrics } from "../src/narrator/metrics.js";
import { getCost } from "../src/narrator/cost.js";
import { getQuota } from "../src/narrator/quota.js";
import { getActivityLog } from "../src/narrator/activity.js";

type Route = [fragment: string, resp: { ok?: boolean; status?: number; json?: unknown; text?: string }];

function stubFetch(routes: Route[]): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const u = String(url);
      for (const [frag, resp] of routes) {
        if (u.includes(frag)) {
          return {
            ok: resp.ok ?? true,
            status: resp.status ?? 200,
            statusText: "",
            async json() {
              return resp.json ?? {};
            },
            async text() {
              return resp.text ?? "";
            },
          };
        }
      }
      return { ok: false, status: 404, statusText: "NF", async json() {}, async text() {
        return "no route";
      } };
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("queryInventory (Resource Graph)", () => {
  it("formats rows as key=value lines", async () => {
    stubFetch([
      ["Microsoft.ResourceGraph", { json: { count: 2, data: [{ name: "rg-a", location: "koreacentral" }, { name: "rg-b", location: "eastus" }] } }],
    ]);
    const out = await queryInventory("ResourceContainers | project name, location");
    expect(out).toContain("name=rg-a");
    expect(out).toContain("location=koreacentral");
  });

  it("returns a friendly message on empty data", async () => {
    stubFetch([["Microsoft.ResourceGraph", { json: { count: 0, data: [] } }]]);
    expect(await queryInventory("Resources | limit 0")).toBe("no matching resources");
  });

  it("throws on a non-2xx response (fail-closed)", async () => {
    stubFetch([["Microsoft.ResourceGraph", { ok: false, status: 500, text: "boom" }]]);
    await expect(queryInventory("Resources")).rejects.toThrow(/Resource Graph 500/);
  });
});

describe("getMetrics (Azure Monitor)", () => {
  it("requires a full ARM id", async () => {
    stubFetch([]);
    expect(await getMetrics("not-an-id", "cpu_percent")).toContain("full ARM id");
  });

  it("summarizes the most recent average and peak", async () => {
    stubFetch([
      [
        "microsoft.insights/metrics",
        {
          json: {
            value: [
              {
                name: { value: "cpu_percent" },
                unit: "Percent",
                timeseries: [{ data: [{ average: 10, maximum: 20 }, { average: 30, maximum: 40 }] }],
              },
            ],
          },
        },
      ],
    ]);
    const out = await getMetrics("/subscriptions/x/resourceGroups/y/providers/p/r", "cpu_percent");
    expect(out).toContain("cpu_percent");
    expect(out).toContain("avg 30");
    expect(out).toContain("peak 40");
  });
});

describe("getCost (Cost Management)", () => {
  it("reports the total and top groups", async () => {
    stubFetch([
      [
        "Microsoft.CostManagement",
        {
          json: {
            properties: {
              columns: [{ name: "Cost" }, { name: "ResourceGroupName" }, { name: "Currency" }],
              rows: [[100, "rg-a", "USD"], [50, "rg-b", "USD"]],
            },
          },
        },
      ],
    ]);
    const out = await getCost("MonthToDate", "ResourceGroupName");
    expect(out).toContain("total 150.00 USD");
    expect(out).toContain("rg-a 100.00");
  });
});

describe("getQuota (Compute usages)", () => {
  it("derives the region and sorts by utilization", async () => {
    stubFetch([
      ["Microsoft.ResourceGraph", { json: { data: [{ location: "koreacentral" }] } }],
      [
        "Microsoft.Compute/locations",
        {
          json: {
            value: [
              { name: { localizedValue: "Total Regional vCPUs" }, currentValue: 44, limit: 600 },
              { name: { localizedValue: "Low-priority vCPUs" }, currentValue: 24, limit: 100 },
            ],
          },
        },
      ],
    ]);
    const out = await getQuota();
    expect(out).toContain("koreacentral");
    // 24% utilization sorts before 7%.
    expect(out.indexOf("Low-priority")).toBeLessThan(out.indexOf("Total Regional"));
  });
});

describe("getActivityLog", () => {
  it("filters to failed operations", async () => {
    stubFetch([
      [
        "microsoft.insights/eventtypes",
        {
          json: {
            value: [
              { eventTimestamp: "2026-07-08T00:00:00Z", status: { value: "Failed" }, operationName: { localizedValue: "Deploy template" } },
              { eventTimestamp: "2026-07-08T00:01:00Z", status: { value: "Succeeded" }, operationName: { localizedValue: "Read secret" } },
            ],
          },
        },
      ],
    ]);
    const out = await getActivityLog(24, "failed");
    expect(out).toContain("Deploy template");
    expect(out).not.toContain("Read secret");
  });
});
