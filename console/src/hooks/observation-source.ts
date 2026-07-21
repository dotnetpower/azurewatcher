import { t } from "../i18n";

export type FrameSource = "unknown" | "synthetic-dev" | "replay" | "runtime-observed";
export type ObservationSource = FrameSource | "mixed";

const KNOWN = new Set<FrameSource>([
  "unknown",
  "synthetic-dev",
  "replay",
  "runtime-observed",
]);

export function normalizeObservationSource(value: unknown): FrameSource {
  return typeof value === "string" && KNOWN.has(value as FrameSource)
    ? value as FrameSource
    : "unknown";
}

export function mergeObservationSource(
  current: ObservationSource,
  incoming: FrameSource,
): ObservationSource {
  if (incoming === "unknown") return current;
  if (current === "unknown") return incoming;
  return current === incoming ? current : "mixed";
}

export function observationSourceLabel(source: ObservationSource): string {
  if (source === "synthetic-dev") return t("observationSource.syntheticDev");
  if (source === "replay") return t("observationSource.replay");
  if (source === "runtime-observed") return t("observationSource.runtimeObserved");
  if (source === "mixed") return t("observationSource.mixed");
  return t("observationSource.unavailable");
}
