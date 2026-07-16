import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, DataTable, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState, type Column } from "../components/ui";
import { t } from "../i18n";
import { panelArray, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

interface Capability {
  readonly capability_id: string;
  readonly name: string;
  readonly category: string;
  readonly summary: string;
  readonly side_effect_class: string;
  readonly default_mode: string;
  readonly required_role: string;
  readonly slide_ref: string;
  readonly tags: readonly string[];
}

interface CapabilityResponse {
  readonly count: number;
  readonly capabilities: readonly Capability[];
}

export function CapabilitiesRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<CapabilityResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/capabilities")
      .then((value) => { if (!cancelled) setState({ status: "ready", data: decodeCapabilities(value) }); })
      .catch((error: unknown) => { if (!cancelled) setState({ status: "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.capabilities")} subtitle={t("nav.panelSub.capabilities")} /><AsyncBoundary state={state} resourceLabel="capabilities">{(data) => <CapabilitiesBody data={data} />}</AsyncBoundary></div>;
}

export function decodeCapabilities(value: unknown): CapabilityResponse {
  const root = panelRecord(value, "capabilities");
  return {
    count: panelNumber(root, "count", "capabilities"),
    capabilities: panelArray(root["capabilities"], "capabilities.items").map((raw, index) => {
      const item = panelRecord(raw, `capabilities.items[${index}]`);
      return {
        capability_id: panelString(item, "capability_id", "capability"),
        name: panelString(item, "name", "capability"),
        category: panelString(item, "category", "capability"),
        summary: panelString(item, "summary", "capability"),
        side_effect_class: panelString(item, "side_effect_class", "capability"),
        default_mode: panelString(item, "default_mode", "capability"),
        required_role: panelString(item, "required_role", "capability"),
        slide_ref: panelString(item, "slide_ref", "capability"),
        tags: panelStringArray(item["tags"], "capability.tags"),
      };
    }),
  };
}

const columns: readonly Column<Capability>[] = [
  { key: "name", header: "Capability", render: (row) => row.name },
  { key: "category", header: "Category", render: (row) => row.category },
  { key: "effect", header: "Side effect", render: (row) => <StatusPill kind={row.side_effect_class === "read" ? "info" : "warning"} label={row.side_effect_class} /> },
  { key: "mode", header: "Default mode", render: (row) => <StatusPill kind={row.default_mode === "shadow" ? "shadow" : "enforce"} label={row.default_mode} /> },
  { key: "role", header: "Required role", render: (row) => row.required_role },
  { key: "summary", header: "Summary", render: (row) => row.summary },
];

function CapabilitiesBody({ data }: { readonly data: CapabilityResponse }) {
  const categories = new Set(data.capabilities.map((item) => item.category)).size;
  const writes = data.capabilities.filter((item) => item.side_effect_class !== "read").length;
  return <div class="stack"><KpiGrid><KpiCard label="Capabilities" value={data.count.toLocaleString()} /><KpiCard label="Categories" value={categories.toLocaleString()} /><KpiCard label="Write-class" value={writes.toLocaleString()} /></KpiGrid><DataTable rows={data.capabilities} columns={columns} keyOf={(row) => row.capability_id} empty="No capabilities registered" /></div>;
}
