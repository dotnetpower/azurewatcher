/**
 * Ontology graph shared data model - node / edge shapes returned by
 * `/ontology/graph`, the semantic cluster palette, and the small pure
 * helpers that classify a type name or format a cardinality.
 *
 * SRP: data + classification only. No React, no canvas, no I/O.
 * Extracted from `ontology-graph.tsx` so the canvas, layout, and focus
 * modules can share one definition without cross-imports.
 */

// ---------------------------------------------------------------------------
// Public API (surfaced through `ontology-graph.tsx` for import stability)
// ---------------------------------------------------------------------------

export interface OntologyNode {
  readonly name: string;
  readonly key: string;
  readonly property_count: number;
  readonly properties: readonly string[];
  readonly description: string | null;
}

export interface OntologyEdge {
  readonly name: string;
  readonly from_type: string;
  readonly to_type: string;
  readonly cardinality: string;
  readonly is_transitive: boolean;
  readonly is_causal: boolean;
  readonly temporal_order: boolean;
  readonly description: string | null;
}

// ---------------------------------------------------------------------------
// Semantic clustering + colour palette
// ---------------------------------------------------------------------------

export type Cluster = "sensor" | "brain" | "action" | "target" | "record" | "other";

export interface ClusterMeta {
  readonly id: Cluster;
  readonly label: string;
  readonly hex: string;
}

// Deep, saturated jewel tones - reads as "glass over anodized metal"
// rather than the washed-out pastels that made cards feel disabled.
export const CLUSTERS: Readonly<Record<Cluster, ClusterMeta>> = {
  sensor: { id: "sensor", label: "Sensors", hex: "#0e9bad" },
  brain: { id: "brain", label: "Knowledge", hex: "#3b82f6" },
  action: { id: "action", label: "Decisions", hex: "#e07b39" },
  target: { id: "target", label: "Targets", hex: "#16a34a" },
  record: { id: "record", label: "Records", hex: "#8b5cf6" },
  other: { id: "other", label: "Other", hex: "#64748b" },
};

export function clusterOf(name: string): Cluster {
  if (/^(Signal|SecurityEvent|Metric|Event)$/i.test(name)) return "sensor";
  if (/^(Rule|Agent|RuleCandidate|Conversation)$/i.test(name)) return "brain";
  if (/^(Finding|Action|HandoffEscalation|Issue|Verdict|Decision)$/i.test(name))
    return "action";
  if (/^(Resource|Cluster|Deployment|Service|Subscription)$/i.test(name))
    return "target";
  if (/^(ChangeSummary|AuditEntry|Report|Trace|Bitemporal|Snapshot)$/i.test(name))
    return "record";
  return "other";
}

export function shortCard(c: string): string {
  const s = c.toLowerCase();
  if (s.includes("many_to_many")) return "*..*";
  if (s.includes("one_to_many")) return "1..*";
  if (s.includes("many_to_one")) return "*..1";
  if (s.includes("one_to_one")) return "1..1";
  return c;
}

// ---------------------------------------------------------------------------
// force-graph node / link shapes (internal to the graph runtime)
// ---------------------------------------------------------------------------

export interface GraphNodeDatum {
  id: string;
  name: string;
  cluster: Cluster;
  color: string;
  propertyCount: number;
  outCount: number;
  inCount: number;
  degree: number;
  properties: readonly string[];
  /** first-N outgoing links, formatted like "applies_to → Resource" */
  outgoingLines: readonly string[];
  /** first-N incoming links, formatted like "Rule → applies_to" */
  incomingLines: readonly string[];
  description: string | null;
  key: string;
  /** cached card width (px), stable across frames */
  _w?: number;
  /** cached card height (px) - varies per node based on content */
  _h?: number;
  /** depth layer - "front" is fully rendered, "back" is scaled and
   *  faded so it feels one plane behind the front cards. */
  layer: "front" | "back";
  /** true when this node has at least one self-reference. Self-refs
   *  render as a small `↷` badge on the card instead of a full
   *  3D loop link - see drawNodeChip. */
  hasSelfRef: boolean;
  x?: number;
  y?: number;
  z?: number;
}

export interface GraphLinkDatum {
  source: string | GraphNodeDatum;
  target: string | GraphNodeDatum;
  label: string;
  color: string;
  isCausal: boolean;
  /** row index of this link inside the source card's outgoing list. */
  outgoingIndex: number;
  /** row index of this link inside the target card's incoming list. */
  incomingIndex: number;
}
