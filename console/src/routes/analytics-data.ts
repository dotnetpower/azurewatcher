import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import type { AutonomyPayload, DashboardKpi, FinOpsPayload } from "../types";
import type { AsyncState } from "../components/ui";
import type { GatesSummary } from "./dashboard.model";

export interface AnalyticsData {
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly finops: FinOpsPayload | null;
  readonly gates: GatesSummary | null;
}

async function optional<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ReadApiError && (error.status === 404 || error.status === 501)) {
      return null;
    }
    throw error;
  }
}

export function useAnalyticsData(client: ReadApiClient): AsyncState<AnalyticsData> {
  const [state, setState] = useState<AsyncState<AnalyticsData>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [kpi, autonomy, finops, gates] = await Promise.all([
          client.dashboardMetrics(),
          optional(() => client.autonomy()),
          optional(() => client.finops()),
          optional(() => client.panel<GatesSummary>("/kpi/promotion-gates")),
        ]);
        if (!cancelled) setState({ status: "ready", data: { kpi, autonomy, finops, gates } });
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client]);
  return state;
}