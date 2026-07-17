import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

interface OnboardingResponse {
  readonly probe_mode: "configured" | "not-configured";
  readonly ready: boolean;
  readonly blocked: boolean;
  readonly missing_resources: readonly string[];
  readonly missing_role_assignments: readonly (readonly string[])[];
  readonly present_resource_count: number;
  readonly present_role_count: number;
  readonly error: string | null;
}

export function OnboardingRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<OnboardingResponse>>({ status: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const generation = useRef(0);
  const load = async (showLoading: boolean): Promise<void> => {
    const request = ++generation.current;
    if (showLoading) setState({ status: "loading" });
    try {
      const data = decodeOnboarding(await client.panel<unknown>("/onboarding"));
      if (request !== generation.current) return;
      setState({ status: "ready", data });
      setCheckedAt(new Date().toISOString());
    } catch (error) {
      if (request !== generation.current) return;
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    }
  };
  useEffect(() => {
    void load(true);
    return () => { generation.current += 1; };
  }, [client]);
  return (
    <div class="stack onboarding-route">
      <PageHeader
        title={t("route.onboarding")}
        subtitle={t("nav.panelSub.onboarding")}
        actions={<button type="button" onClick={() => { void load(false); }}>Refresh</button>}
      />
      <AsyncBoundary state={state} resourceLabel="onboarding readiness">
        {(data) => <OnboardingBody data={data} checkedAt={checkedAt} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeOnboarding(value: unknown): OnboardingResponse {
  const root = panelRecord(value, "onboarding");
  const probeMode = panelString(root, "probe_mode", "onboarding");
  if (probeMode !== "configured" && probeMode !== "not-configured") {
    throw new Error("onboarding.probe_mode MUST be configured or not-configured");
  }
  const error = root["error"];
  if (error !== undefined && error !== null && typeof error !== "string") {
    throw new Error("onboarding.error MUST be a string or null");
  }
  return {
    probe_mode: probeMode,
    ready: panelBoolean(root, "ready", "onboarding"),
    blocked: panelBoolean(root, "blocked", "onboarding"),
    missing_resources: panelStringArray(root["missing_resources"], "onboarding.missing_resources"),
    missing_role_assignments: panelArray(root["missing_role_assignments"], "onboarding.missing_role_assignments").map((item, index) => panelStringArray(item, `onboarding.missing_role_assignments[${index}]`)),
    present_resource_count: panelNumber(root, "present_resource_count", "onboarding"),
    present_role_count: panelNumber(root, "present_role_count", "onboarding"),
    error: typeof error === "string" ? error : null,
  };
}

function OnboardingBody({ data, checkedAt }: { readonly data: OnboardingResponse; readonly checkedAt: string | null }) {
  const observed = data.probe_mode === "configured" && data.error === null;
  usePublishViewContext(
    () => ({
      routeId: "onboarding",
      routeLabel: "Onboarding",
      purpose: "Checks whether required runtime resources and executor role assignments are present before FDAI can operate.",
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: !observed
        ? "Onboarding readiness is unavailable"
        : data.ready
        ? "Onboarding prerequisites are ready"
        : `${data.missing_resources.length} resource gap(s), ${data.missing_role_assignments.length} role gap(s)`,
      capturedAt: checkedAt ?? new Date().toISOString(),
      facts: [
        { key: "probe_mode", value: data.probe_mode, group: "readiness" },
        { key: "ready", value: observed ? data.ready : null, group: "readiness" },
        { key: "resources_observed", value: observed ? data.present_resource_count : null, group: "readiness" },
        { key: "roles_observed", value: observed ? data.present_role_count : null, group: "readiness" },
        { key: "probe_error", value: data.error, group: "readiness" },
      ],
      records: {
        [observed ? "missing_resources" : "required_resources"]:
          data.missing_resources.map((resource) => ({ resource })),
        [observed ? "missing_role_assignments" : "required_role_assignments"]:
          data.missing_role_assignments.map(([principal, role, target]) => ({ principal, role, target })),
      },
    }),
    [checkedAt, data],
  );
  return (
    <div class="stack">
      {data.probe_mode === "not-configured" ? (
        <div class="state-block state-unavailable" role="status">
          <span class="state-icon" aria-hidden="true">?</span>
          <span>The Azure onboarding probe is not configured. These gaps describe the required baseline, not observed tenant state.</span>
        </div>
      ) : null}
      {data.error !== null ? (
        <div class="state-block state-unavailable" role="alert">
          <span class="state-icon" aria-hidden="true">!</span>
          <span>The configured Azure onboarding probe failed. No tenant readiness observation is available. {data.error}</span>
        </div>
      ) : null}
      <KpiGrid>
        <KpiCard label="Readiness" value={observed ? <StatusPill kind={data.ready ? "success" : "danger"} label={data.ready ? "ready" : "blocked"} /> : "-"} />
        <KpiCard label="Resources observed" value={observed ? data.present_resource_count.toLocaleString() : "-"} />
        <KpiCard label="Roles observed" value={observed ? data.present_role_count.toLocaleString() : "-"} />
        <KpiCard label="Last checked" value={checkedAt ? new Date(checkedAt).toLocaleTimeString() : "-"} />
      </KpiGrid>
      <nav class="onboarding-actions" aria-label="Onboarding drilldowns">
        <a href={routeHref("provision")}>Open provisioning</a>
        <a href={routeHref("settings-iam", { segments: ["requests"] })}>Review access requests</a>
        <a href={routeHref("architecture")}>Inspect architecture</a>
      </nav>
      <section class="stack-section">
        <h3 class="section-title">{observed ? "Missing resources" : "Required resources"} ({data.missing_resources.length})</h3>
        {data.missing_resources.length ? (
          <ul class="onboarding-gap-list">
            {data.missing_resources.map((resource) => <li key={resource}><code>{resource}</code></li>)}
          </ul>
        ) : <p class="muted">None</p>}
      </section>
      <section class="stack-section">
        <h3 class="section-title">{observed ? "Missing role assignments" : "Required role assignments"} ({data.missing_role_assignments.length})</h3>
        {data.missing_role_assignments.length ? (
          <ul class="onboarding-role-list">
            {data.missing_role_assignments.map(([principal, role, target]) => (
              <li key={`${principal}:${role}:${target}`}>
                <code>{principal}</code><span>{role}</span><code>{target}</code>
              </li>
            ))}
          </ul>
        ) : <p class="muted">None</p>}
      </section>
    </div>
  );
}
