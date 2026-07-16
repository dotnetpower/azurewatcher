import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { t } from "../i18n";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelStringArray } from "./panel-decode";

interface OnboardingResponse {
  readonly ready: boolean;
  readonly blocked: boolean;
  readonly missing_resources: readonly string[];
  readonly missing_role_assignments: readonly (readonly string[])[];
  readonly present_resource_count: number;
  readonly present_role_count: number;
}

export function OnboardingRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<OnboardingResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/onboarding")
      .then((value) => { if (!cancelled) setState({ status: "ready", data: decodeOnboarding(value) }); })
      .catch((error: unknown) => { if (!cancelled) setState({ status: "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.onboarding")} subtitle={t("nav.panelSub.onboarding")} /><AsyncBoundary state={state} resourceLabel="onboarding readiness">{(data) => <OnboardingBody data={data} />}</AsyncBoundary></div>;
}

export function decodeOnboarding(value: unknown): OnboardingResponse {
  const root = panelRecord(value, "onboarding");
  return {
    ready: panelBoolean(root, "ready", "onboarding"),
    blocked: panelBoolean(root, "blocked", "onboarding"),
    missing_resources: panelStringArray(root["missing_resources"], "onboarding.missing_resources"),
    missing_role_assignments: panelArray(root["missing_role_assignments"], "onboarding.missing_role_assignments").map((item, index) => panelStringArray(item, `onboarding.missing_role_assignments[${index}]`)),
    present_resource_count: panelNumber(root, "present_resource_count", "onboarding"),
    present_role_count: panelNumber(root, "present_role_count", "onboarding"),
  };
}

function OnboardingBody({ data }: { readonly data: OnboardingResponse }) {
  return <div class="stack"><KpiGrid><KpiCard label="Readiness" value={<StatusPill kind={data.ready ? "success" : "danger"} label={data.ready ? "ready" : "blocked"} />} /><KpiCard label="Resources observed" value={data.present_resource_count.toLocaleString()} /><KpiCard label="Roles observed" value={data.present_role_count.toLocaleString()} /></KpiGrid><section class="stack"><h3>Missing resources</h3><p class="mono muted">{data.missing_resources.length ? data.missing_resources.join(", ") : "None"}</p></section><section class="stack"><h3>Missing role assignments</h3><p class="mono muted">{data.missing_role_assignments.length ? data.missing_role_assignments.map((item) => item.join(" / ")).join(", ") : "None"}</p></section></div>;
}
