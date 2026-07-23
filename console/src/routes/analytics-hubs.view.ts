import type { ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import type { AutonomyPayload, MetricVsBaseline } from "../types";

interface OperatingOutcomeSnapshotInput {
  readonly autonomy: AutonomyPayload;
  readonly metric: MetricVsBaseline;
  readonly metricKey: string;
  readonly metricLabel: string;
  readonly unavailableLabel: string;
  readonly routeLabel: string;
}

export function buildOperatingOutcomeViewSnapshot({
  autonomy,
  metric,
  metricKey,
  metricLabel,
  unavailableLabel,
  routeLabel,
}: OperatingOutcomeSnapshotInput): ViewSnapshot {
  const current = metric.value ?? unavailableLabel;
  const baseline = metric.baseline ?? unavailableLabel;
  return {
    routeId: "operating-outcomes",
    routeLabel,
    purpose:
      "Inspect measured operating outcomes, their baselines and trends, and the evidence " +
      "contributed by each operational vertical.",
    headline:
      `${metricLabel}: current ${current}, baseline ${baseline}; ` +
      `${autonomy.sample_size} events over ${autonomy.window_days} days.`,
    capturedAt: autonomy.source.as_of ?? new Date().toISOString(),
    glossary: composeGlossary([
      {
        term: "measured evidence",
        plain: "observations computed from the named source over the displayed window",
      },
      {
        term: "baseline",
        plain: "the reference measurement used to compare the current outcome",
      },
      {
        term: "confidence",
        plain: "the statistical confidence reported by the measurement source when available",
      },
    ]),
    facts: [
      { key: "selected_metric", label: metricLabel, value: metricKey, group: "metric" },
      {
        key: "current_value",
        label: "Current",
        aliases: [metricLabel, metricKey],
        value: metric.value,
        group: "metric",
      },
      {
        key: "baseline_value",
        label: "Baseline",
        aliases: [`${metricLabel} baseline`],
        value: metric.baseline,
        group: "metric",
      },
      { key: "direction", label: "Better when", value: metric.direction, group: "metric" },
      { key: "window_days", label: "Measurement window", value: autonomy.window_days, group: "evidence" },
      { key: "sample_size", label: "Sample size", value: autonomy.sample_size, group: "evidence" },
      { key: "confidence", label: "Confidence", value: autonomy.confidence, group: "evidence" },
      { key: "source", label: "Evidence source", value: autonomy.source.name, group: "evidence" },
      { key: "source_kind", value: autonomy.source.kind, group: "evidence" },
      { key: "source_as_of", label: "Evidence as of", value: autonomy.source.as_of, group: "evidence" },
      { key: "synthetic", value: autonomy.synthetic, group: "evidence" },
    ],
    records: {
      verticals: autonomy.verticals.map((vertical) => ({ ...vertical })),
    },
    explanations: {
      provenance: {
        authority: autonomy.source.kind,
        refs: [autonomy.source.name],
      },
    },
  };
}
