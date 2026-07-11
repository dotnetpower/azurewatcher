/**
 * Ontology graph layout math - card sizing, effective on-screen scale,
 * row-anchor offsets for links, and the "which node has focus?" seed.
 *
 * SRP: pure geometry. No React, no canvas. Extracted from
 * `ontology-graph.tsx` so the canvas-draw and main-component modules
 * can share the same layout numbers without duplicating them.
 */

import type { OntologyEdge, OntologyNode } from "./ontology-graph.types";

// ---------------------------------------------------------------------------
// Card sizing constants
// ---------------------------------------------------------------------------

// Card sizing: width is fixed for a tidy grid feel; height is
// *computed per node* from how many items each section previews.
// Typography and geometry are tuned so text reads clearly at the
// 3D camera distance without needing the viewer to zoom in.
export const CARD_W = 180;
export const HEADER_H = 28;
export const BODY_PAD_Y = 8;
export const SECTION_LABEL_H = 16; // "P 5 properties" line
export const SECTION_PAD = 4;      // trailing gap after each section
export const ROW_H = 14;           // per preview item line
// Long lists are capped to keep cards from towering over the scene
// and, on click focus, from overlapping their vertical neighbours
// once the sprite scale animates to layer 1. Overflow rows show up
// as a compact "+N more" line and any link that would have anchored
// beyond the cap collapses onto that line.
export const MAX_ITEMS_PER_SECTION = 4;

// Back-layer cards are drawn at this scale so they visually recede.
// The value picks a size ratio subtle enough to still read text but
// clear enough that the depth is obvious at a glance.
export const BACK_LAYER_SCALE = 0.78;
export const BACK_LAYER_ALPHA = 0.78;

// 3D sprite scale per node. Front cards render slightly larger than
// back cards so the depth planes read at a glance even without
// perspective. Kept as a single source of truth so the link anchor
// math and the sprite factory always agree.
//
// On click, focused cards animate their scale up to FRONT_SPRITE_SCALE
// (matching layer 1) - the animation stores the current scale on
// ``node._currentSpriteScale`` so this getter, and therefore every
// anchor helper, immediately reflects the new size.
export const FRONT_SPRITE_SCALE = 0.78;
export const BACK_SPRITE_SCALE = 0.62;

// ---------------------------------------------------------------------------
// Card measurement
// ---------------------------------------------------------------------------

export function cardHeightFor(propCount: number, outCount: number, inCount: number): number {
  const sectionH = (items: number) => {
    const shown = Math.min(items, MAX_ITEMS_PER_SECTION);
    const overflow = items - shown;
    const rows = Math.max(1, shown + (overflow > 0 ? 1 : 0));
    return SECTION_LABEL_H + rows * ROW_H + SECTION_PAD;
  };
  return (
    HEADER_H + BODY_PAD_Y +
    sectionH(propCount) + sectionH(outCount) + sectionH(inCount) +
    BODY_PAD_Y
  );
}

export function nodeW(n: any): number {
  return (n?._w ?? CARD_W) as number;
}
export function nodeH(n: any): number {
  const h = n?._h;
  return (typeof h === "number" && h > 0 ? h : 140) as number;
}

export function nodeScale(n: any): number {
  return n?.layer === "back" ? BACK_LAYER_SCALE : 1;
}
/** Effective on-screen half-width (accounts for layer scale). */
export function nodeHalfW(n: any): number {
  return (nodeW(n) * nodeScale(n)) / 2;
}
/** Effective on-screen half-height (accounts for layer scale). */
export function nodeHalfH(n: any): number {
  return (nodeH(n) * nodeScale(n)) / 2;
}

export function baseSpriteScale(n: any): number {
  return n?.layer === "back" ? BACK_SPRITE_SCALE : FRONT_SPRITE_SCALE;
}
export function nodeSpriteScale(n: any): number {
  const overridden = n?._currentSpriteScale;
  if (typeof overridden === "number" && overridden > 0) return overridden;
  return baseSpriteScale(n);
}

// ---------------------------------------------------------------------------
// Row-anchor offsets
// ---------------------------------------------------------------------------

/**
 * Y-offset from a card's centre to the vertical middle of a specific
 * body row, in world units (already includes the sprite scale).
 *
 * The row layout inside a card is:
 *   HEADER_H
 *   BODY_PAD_Y
 *   [Properties label + propRows * ROW_H + SECTION_PAD]
 *   [Outgoing   label + outRows  * ROW_H + SECTION_PAD]
 *   [Incoming   label + inRows   * ROW_H + SECTION_PAD]
 *   BODY_PAD_Y
 *
 * We walk that layout to find the target row and return
 * ``(h/2 - yFromTop) * scale``. Up is positive.
 */
export function rowYOffset(
  node: any,
  section: "out" | "in",
  rowIdx: number,
): number {
  const h = nodeH(node);
  const scale = nodeSpriteScale(node);
  const propRows = Math.max(1, (node.properties?.length ?? 0));
  const outRows = Math.max(1, node.outCount ?? 0);
  // Overflow rows collapse onto the "+N more" line at position
  // MAX_ITEMS_PER_SECTION. To avoid every overflow link stacking on
  // exactly the same y (which produces the bundled "hot spot" the
  // user reported), each overflow index gets a small per-index Y
  // stagger so multiple hidden links spread out visibly across the
  // "+N more" line's vertical footprint.
  const isOverflow = rowIdx >= MAX_ITEMS_PER_SECTION;
  const clampedIdx = Math.min(rowIdx, MAX_ITEMS_PER_SECTION);
  const clampedPropRows =
    Math.min(propRows, MAX_ITEMS_PER_SECTION) +
    (propRows > MAX_ITEMS_PER_SECTION ? 1 : 0);
  const clampedOutRows =
    Math.min(outRows, MAX_ITEMS_PER_SECTION) +
    (outRows > MAX_ITEMS_PER_SECTION ? 1 : 0);
  let yFromTop = HEADER_H + BODY_PAD_Y;
  // Properties block precedes both outgoing and incoming.
  yFromTop += SECTION_LABEL_H + clampedPropRows * ROW_H + SECTION_PAD;
  if (section === "in") {
    yFromTop += SECTION_LABEL_H + clampedOutRows * ROW_H + SECTION_PAD;
  }
  yFromTop += SECTION_LABEL_H + clampedIdx * ROW_H + ROW_H / 2;
  // Overflow stagger: spread each overflow index by ~6 px in Y so
  // multiple hidden links visibly fan out below the "+N more" line
  // instead of all bundling onto the exact same anchor point.
  if (isOverflow) {
    const overflowOrder = rowIdx - MAX_ITEMS_PER_SECTION;
    yFromTop += (overflowOrder - 1) * 6;
  }
  return (h / 2 - yFromTop) * scale;
}

/**
 * World-space anchor point for the start of an outgoing link.
 * ``side`` picks which vertical edge the link leaves from: -1 = left,
 * +1 = right. updateLinkEndpoints chooses the side that faces the
 * target card so the line flows DIRECTLY toward its destination
 * instead of every link bundling onto the left edge and arcing back.
 * The vertical offset still lands on the named text row so the arrow
 * visibly sprouts from the row that labels it.
 */
export function anchorForOutgoing(
  node: any,
  outIndex: number,
  side: -1 | 1 = -1,
): { x: number; y: number; z: number } {
  const scale = nodeSpriteScale(node);
  const xOff = (side * (nodeW(node) * scale)) / 2;
  const yOff = rowYOffset(node, "out", outIndex);
  return {
    x: (node.x ?? 0) + xOff,
    y: (node.y ?? 0) + yOff,
    z: node.z ?? 0,
  };
}

/**
 * World-space anchor point for the end of an incoming link. ``side``
 * mirrors anchorForOutgoing: the target receives the line on the edge
 * that faces the source card (-1 = left, +1 = right).
 */
export function anchorForIncoming(
  node: any,
  inIndex: number,
  side: -1 | 1 = -1,
): { x: number; y: number; z: number } {
  const scale = nodeSpriteScale(node);
  const xOff = (side * (nodeW(node) * scale)) / 2;
  const yOff = rowYOffset(node, "in", inIndex);
  return {
    x: (node.x ?? 0) + xOff,
    y: (node.y ?? 0) + yOff,
    z: node.z ?? 0,
  };
}

// ---------------------------------------------------------------------------
// Link-hover involvement predicate
// ---------------------------------------------------------------------------

export function isInvolved(link: any, hoverId: string | null): boolean {
  if (hoverId === null) return false;
  const src = typeof link.source === "string" ? link.source : link.source.id;
  const tgt = typeof link.target === "string" ? link.target : link.target.id;
  return src === hoverId || tgt === hoverId;
}

// ---------------------------------------------------------------------------
// Initial focus seed
// ---------------------------------------------------------------------------

export function initialFocus(
  nodes: readonly OntologyNode[],
  edges: readonly OntologyEdge[],
): string {
  const deg = new Map<string, number>();
  for (const n of nodes) deg.set(n.name, 0);
  for (const e of edges) {
    deg.set(e.from_type, (deg.get(e.from_type) ?? 0) + 1);
    deg.set(e.to_type, (deg.get(e.to_type) ?? 0) + 1);
  }
  let best = nodes[0]?.name ?? "";
  let bestDeg = -1;
  for (const [name, d] of deg) {
    if (d > bestDeg) {
      bestDeg = d;
      best = name;
    }
  }
  return best;
}
