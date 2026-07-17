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
  if (source === "synthetic-dev") return "Generated sample";
  if (source === "replay") return "Scenario replay";
  if (source === "runtime-observed") return "Runtime observed";
  if (source === "mixed") return "Mixed sources";
  return "Source unavailable";
}
