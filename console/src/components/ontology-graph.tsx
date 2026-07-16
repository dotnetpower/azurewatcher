/**
 * Deterministic one-hop ontology renderer.
 *
 * The selected ObjectType stays in the center, incoming relations render on
 * the left, outgoing relations render on the right, and self-links loop above
 * the selected card. The graph is presentation-only and keeps the existing
 * right-column focus panel for properties and complete relationship details.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { FocusCard } from "./ontology-graph.focus";
import {
  buildOntologyNeighborhood,
  type OntologyRelation,
} from "./ontology-graph.model";
import {
  CLUSTERS,
  clusterOf,
  shortCard,
  type OntologyEdge,
  type OntologyNode,
} from "./ontology-graph.types";

export type { OntologyEdge, OntologyNode } from "./ontology-graph.types";

interface Props {
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly initialName?: string | null;
  readonly onFocusChange?: (name: string | null) => void;
  readonly onLinkSelect: ((name: string) => void) | undefined;
}

interface Point {
  readonly x: number;
  readonly y: number;
}

const VIEW_WIDTH = 760;
const CARD_WIDTH = 164;
const CARD_HEIGHT = 58;
const ROW_GAP = 26;
const LEFT_X = 10;
const FOCUS_X = 298;
const RIGHT_X = 586;

export function OntologyGraph({ nodes, edges, initialName = null, onFocusChange, onLinkSelect }: Props) {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const neighborhood = useMemo(
    () => buildOntologyNeighborhood(nodes, edges, initialName),
    [nodes, edges, initialName],
  );
  const [hoveredName, setHoveredName] = useState<string | null>(null);
  const focus = neighborhood.focus;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && canvas.scrollWidth > canvas.clientWidth) {
      canvas.scrollLeft = (canvas.scrollWidth - canvas.clientWidth) / 2;
    }
  }, [focus?.name]);

  if (!focus) {
    return <p class="ontology-graph-empty muted">No ObjectTypes are registered.</p>;
  }

  const rowCount = Math.max(neighborhood.incoming.length, neighborhood.outgoing.length, 4);
  const height = Math.max(410, rowCount * CARD_HEIGHT + (rowCount - 1) * ROW_GAP + 72);
  const focusY = (height - CARD_HEIGHT) / 2;
  const contentLeft = neighborhood.incoming.length > 0 ? LEFT_X : FOCUS_X;
  const contentRight = neighborhood.outgoing.length > 0
    ? RIGHT_X + CARD_WIDTH
    : FOCUS_X + CARD_WIDTH;
  const contentShiftX = VIEW_WIDTH / 2 - (contentLeft + contentRight) / 2;
  const detailName = hoveredName ?? focus.name;
  const detailNeighborhood = buildOntologyNeighborhood(nodes, edges, detailName);
  const activate = (name: string): void => {
    if (name !== focus.name) onFocusChange?.(name);
  };

  return (
    <div class="ontology-orbit">
      <div class="ontology-orbit-canvas-wrap" ref={canvasRef}>
        <div class="ontology-graph-key" aria-label="Relationship direction legend">
          <span><i class="is-incoming" />Incoming</span>
          <span><i class="is-outgoing" />Outgoing</span>
          <span><i class="is-causal" />Causal link</span>
        </div>
        <svg
          class="ontology-neighborhood-svg"
          viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
          role="group"
          aria-label={`One-hop neighborhood of ${focus.name}`}
        >
          <defs>
            <marker
              id="ontology-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" class="ontology-arrow-head" />
            </marker>
          </defs>

          <g class="ontology-graph-content" transform={`translate(${contentShiftX} 0)`}>
          {neighborhood.incoming.map((relation, index) => (
            <RelationRow
              key={`incoming-line-${relation.node.name}`}
              layer="line"
              relation={relation}
              direction="incoming"
              nodePoint={{ x: LEFT_X, y: rowY(index, neighborhood.incoming.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          {neighborhood.outgoing.map((relation, index) => (
            <RelationRow
              key={`outgoing-line-${relation.node.name}`}
              layer="line"
              relation={relation}
              direction="outgoing"
              nodePoint={{ x: RIGHT_X, y: rowY(index, neighborhood.outgoing.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          {neighborhood.selfLinks.map((edge, index) => (
            <SelfLink key={`self-line-${edge.name}`} layer="line" edge={edge} focusY={focusY} index={index} onLinkSelect={onLinkSelect} />
          ))}

          {neighborhood.incoming.map((relation, index) => (
            <RelationRow
              key={`incoming-label-${relation.node.name}`}
              layer="label"
              relation={relation}
              direction="incoming"
              nodePoint={{ x: LEFT_X, y: rowY(index, neighborhood.incoming.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          {neighborhood.outgoing.map((relation, index) => (
            <RelationRow
              key={`outgoing-label-${relation.node.name}`}
              layer="label"
              relation={relation}
              direction="outgoing"
              nodePoint={{ x: RIGHT_X, y: rowY(index, neighborhood.outgoing.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          {neighborhood.selfLinks.map((edge, index) => (
            <SelfLink key={`self-label-${edge.name}`} layer="label" edge={edge} focusY={focusY} index={index} onLinkSelect={onLinkSelect} />
          ))}

          {neighborhood.incoming.map((relation, index) => (
            <RelationRow
              key={`incoming-node-${relation.node.name}`}
              layer="node"
              relation={relation}
              direction="incoming"
              nodePoint={{ x: LEFT_X, y: rowY(index, neighborhood.incoming.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          {neighborhood.outgoing.map((relation, index) => (
            <RelationRow
              key={`outgoing-node-${relation.node.name}`}
              layer="node"
              relation={relation}
              direction="outgoing"
              nodePoint={{ x: RIGHT_X, y: rowY(index, neighborhood.outgoing.length, height) }}
              focusPoint={{ x: FOCUS_X, y: focusY }}
              focusedName={focus.name}
              hoveredName={hoveredName}
              onHover={setHoveredName}
              onActivate={activate}
              onLinkSelect={onLinkSelect}
            />
          ))}

          <NodeCard
            node={focus}
            point={{ x: FOCUS_X, y: focusY }}
            selected
            hovered={hoveredName === focus.name}
            onHover={setHoveredName}
            onActivate={activate}
          />
          </g>
        </svg>
        <p class="ontology-graph-note muted">
          Select a neighboring ObjectType to move through the registry. Relationship details remain visible in the inspector.
        </p>
      </div>
      <FocusCard
        name={detailName}
        nodes={nodes}
        edges={edges}
        neighbourhood={detailNeighborhood.nodeNames}
      />
    </div>
  );
}

function rowY(index: number, count: number, height: number): number {
  const contentHeight = count * CARD_HEIGHT + Math.max(0, count - 1) * ROW_GAP;
  return (height - contentHeight) / 2 + index * (CARD_HEIGHT + ROW_GAP);
}

function RelationRow({
  layer,
  relation,
  direction,
  nodePoint,
  focusPoint,
  focusedName,
  hoveredName,
  onHover,
  onActivate,
  onLinkSelect,
}: {
  readonly layer: "line" | "label" | "node";
  readonly relation: OntologyRelation;
  readonly direction: "incoming" | "outgoing";
  readonly nodePoint: Point;
  readonly focusPoint: Point;
  readonly focusedName: string;
  readonly hoveredName: string | null;
  readonly onHover: (name: string | null) => void;
  readonly onActivate: (name: string) => void;
  readonly onLinkSelect: ((name: string) => void) | undefined;
}) {
  const incoming = direction === "incoming";
  const startX = incoming ? nodePoint.x + CARD_WIDTH : focusPoint.x + CARD_WIDTH;
  const startY = incoming ? nodePoint.y + CARD_HEIGHT / 2 : focusPoint.y + CARD_HEIGHT / 2;
  const endX = incoming ? focusPoint.x : nodePoint.x;
  const endY = incoming ? focusPoint.y + CARD_HEIGHT / 2 : nodePoint.y + CARD_HEIGHT / 2;
  const bend = incoming ? 44 : -44;
  const path = `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`;
  const labelPoint = {
    x: (startX + endX) / 2,
    y: (startY + endY) / 2 - 18,
  };

  if (layer === "line") {
    return (
      <path
        d={path}
        class={`ontology-relation-line is-${direction}${relation.edges.some((edge) => edge.is_causal) ? " is-causal" : ""}`}
        markerEnd="url(#ontology-arrow)"
      />
    );
  }
  if (layer === "label") {
    return <RelationLabel edges={relation.edges} point={labelPoint} onLinkSelect={onLinkSelect} />;
  }
  return (
    <g class={hoveredName === relation.node.name ? "is-hovered" : undefined}>
      <NodeCard
        node={relation.node}
        point={nodePoint}
        selected={relation.node.name === focusedName}
        hovered={relation.node.name === hoveredName}
        onHover={onHover}
        onActivate={onActivate}
      />
    </g>
  );
}

function RelationLabel({
  edges,
  point,
  onLinkSelect,
}: {
  readonly edges: readonly OntologyEdge[];
  readonly point: Point;
  readonly onLinkSelect: ((name: string) => void) | undefined;
}) {
  const primary = edges[0];
  if (!primary) return null;
  const suffix = edges.length > 1 ? ` +${edges.length - 1}` : ` ${shortCard(primary.cardinality)}`;
  const label = `${truncate(primary.name, 17)}${suffix}`;
  return (
    <g
      class={`ontology-relation-label${onLinkSelect ? " is-interactive" : ""}`}
      transform={`translate(${point.x} ${point.y})`}
      role={onLinkSelect ? "link" : undefined}
      tabIndex={onLinkSelect ? 0 : undefined}
      aria-label={onLinkSelect ? `Open LinkType ${primary.name}` : undefined}
      onClick={() => onLinkSelect?.(primary.name)}
      onKeyDown={(event) => {
        if (onLinkSelect && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onLinkSelect(primary.name);
        }
      }}
    >
      <rect x="-59" y="-9" width="118" height="18" rx="4" />
      <text textAnchor="middle" dominantBaseline="middle">{label}</text>
      <title>{edges.map((edge) => `${edge.name} (${edge.cardinality})`).join(", ")}</title>
    </g>
  );
}

function SelfLink({ layer, edge, focusY, index, onLinkSelect }: {
  readonly layer: "line" | "label";
  readonly edge: OntologyEdge;
  readonly focusY: number;
  readonly index: number;
  readonly onLinkSelect: ((name: string) => void) | undefined;
}) {
  const centerX = FOCUS_X + CARD_WIDTH / 2;
  const rise = 60 + index * 44;
  const startX = FOCUS_X + CARD_WIDTH - 28;
  const endX = FOCUS_X + 28;
  const y = focusY;
  const apexY = y - rise * 0.75;
  const path = `M ${startX} ${y} C ${startX + 24} ${y - rise}, ${endX - 24} ${y - rise}, ${endX} ${y}`;
  if (layer === "line") {
    return (
      <path
        d={path}
        class={`ontology-relation-line is-self${edge.is_causal ? " is-causal" : ""}`}
        markerEnd="url(#ontology-arrow)"
      />
    );
  }
  return <RelationLabel edges={[edge]} point={{ x: centerX, y: apexY - 16 }} onLinkSelect={onLinkSelect} />;
}

function NodeCard({
  node,
  point,
  selected,
  hovered,
  onHover,
  onActivate,
}: {
  readonly node: OntologyNode;
  readonly point: Point;
  readonly selected: boolean;
  readonly hovered: boolean;
  readonly onHover: (name: string | null) => void;
  readonly onActivate: (name: string) => void;
}) {
  const cluster = clusterOf(node.name);
  const clusterMeta = CLUSTERS[cluster];
  const activate = (): void => onActivate(node.name);
  return (
    <g
      class={`ontology-node-card is-${cluster}${selected ? " is-selected" : ""}${hovered ? " is-hovered" : ""}`}
      transform={`translate(${point.x} ${point.y})`}
      role="button"
      tabIndex={0}
      aria-label={`${node.name}, ${node.property_count} properties, ${clusterMeta.label}`}
      onMouseEnter={() => onHover(node.name)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(node.name)}
      onBlur={() => onHover(null)}
      onClick={activate}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      }}
    >
      <rect class="ontology-node-surface" width={CARD_WIDTH} height={CARD_HEIGHT} rx="8" />
      <circle class="ontology-node-cluster" cx="17" cy="18" r="5" fill={clusterMeta.hex} />
      <text class="ontology-node-title" x="29" y="22">{truncate(node.name, 19)}</text>
      <text class="ontology-node-meta" x="17" y="43">
        {node.property_count} properties | {clusterMeta.label}
      </text>
      <title>{node.name}: {node.description ?? "No description recorded."}</title>
    </g>
  );
}

function truncate(value: string, maxLength: number): string {
  return value.length > maxLength ? `${value.slice(0, maxLength - 3)}...` : value;
}
