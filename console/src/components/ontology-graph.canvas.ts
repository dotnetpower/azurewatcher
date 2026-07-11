/**
 * Ontology graph canvas primitives - card, edge, arrow, grid, and the
 * small colour helpers (`withAlpha`, `shade`) they rely on.
 *
 * SRP: raw 2D drawing only. No React, no layout math (imported from
 * `ontology-graph.layout.ts`), no data shaping. Extracted from
 * `ontology-graph.tsx` so the ~700 lines of pixel-pushing live away
 * from the component lifecycle they serve.
 */

import type { GraphNodeDatum } from "./ontology-graph.types";
import {
  BACK_LAYER_ALPHA,
  BACK_LAYER_SCALE,
  BODY_PAD_Y,
  HEADER_H,
  MAX_ITEMS_PER_SECTION,
  ROW_H,
  SECTION_LABEL_H,
  SECTION_PAD,
  nodeH,
  nodeHalfH,
  nodeHalfW,
  nodeW,
} from "./ontology-graph.layout";

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

export function withAlpha(hex: string, alpha: number): string {
  if (!hex.startsWith("#") || hex.length !== 7) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Darken (f < 1, toward black) or lighten (f > 1, toward white) a
 * ``#rrggbb`` colour. Used to derive an accessible "ink" shade of a
 * cluster hue for text/icons/borders on a light card, so coloured
 * accents clear the WCAG AA contrast bar instead of ghosting into the
 * same-hue body.
 */
export function shade(hex: string, f: number): string {
  if (!hex.startsWith("#") || hex.length !== 7) return hex;
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  if (f <= 1) {
    return `rgb(${clamp(r * f)}, ${clamp(g * f)}, ${clamp(b * f)})`;
  }
  const t = f - 1;
  return `rgb(${clamp(r + (255 - r) * t)}, ${clamp(g + (255 - g) * t)}, ${clamp(b + (255 - b) * t)})`;
}

/** Seeded PRNG so the initial node scatter is deterministic across
 *  reloads. Mulberry32 - tiny (32-bit state), good enough for jitter. */
export function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------------------
// Path primitives
// ---------------------------------------------------------------------------

export function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

export function roundedRectTop(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x, y + h);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

export function truncateText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  const ellipsis = "…";
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    const candidate = text.slice(0, mid) + ellipsis;
    if (ctx.measureText(candidate).width <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return text.slice(0, lo) + ellipsis;
}

/**
 * Compute the intersection of a segment from ``(cx, cy)`` to ``(x, y)``
 * with the axis-aligned rectangle centred at ``(cx, cy)`` with half
 * extents ``hw`` × ``hh``. Returns the point on the rectangle border
 * along the same line, so an edge that would otherwise pass through
 * the card stops at its border instead.
 */
export function rectBorderPoint(
  cx: number,
  cy: number,
  x: number,
  y: number,
  hw: number,
  hh: number,
): { x: number; y: number } {
  const dx = x - cx;
  const dy = y - cy;
  if (dx === 0 && dy === 0) return { x, y };
  // Parametric: find the smallest t in (0, 1] such that
  // |cx + t*dx - cx| = hw OR |cy + t*dy - cy| = hh.
  const tx = dx === 0 ? Infinity : Math.abs(hw / dx);
  const ty = dy === 0 ? Infinity : Math.abs(hh / dy);
  const t = Math.min(tx, ty);
  return { x: cx + dx * t, y: cy + dy * t };
}

export function drawArrowHead(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  angle: number,
  size: number,
) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-size, -size * 0.5);
  ctx.lineTo(-size, size * 0.5);
  ctx.closePath();
  ctx.fillStyle = ctx.strokeStyle;
  ctx.fill();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Node card
// ---------------------------------------------------------------------------

export function drawNodeChip(
  ctx: CanvasRenderingContext2D,
  node: GraphNodeDatum,
  _globalScale: number,
  opts: {
    readonly labelColor: string;
    readonly mutedColor: string;
    readonly isDark: boolean;
    readonly hoverId: string | null;
    readonly neighbourhood: ReadonlyMap<string, Set<string>>;
    /** Card->light unit vector in canvas space (single global light). */
    readonly lightDir?: { readonly x: number; readonly y: number };
  },
) {
  // Card dims come from the node datum so each card can be a
  // different height depending on how much content it carries.
  const w = nodeW(node);
  const h = nodeH(node);
  const cx = node.x ?? 0;
  const cy = node.y ?? 0;

  // Back-layer cards are scaled around their own centre. We apply
  // the transform once here so the rest of the draw code stays in
  // "virgin" coordinates and does not need to know about depth.
  const isBack = node.layer === "back";
  ctx.save();
  if (isBack) {
    ctx.translate(cx, cy);
    ctx.scale(BACK_LAYER_SCALE, BACK_LAYER_SCALE);
    ctx.translate(-cx, -cy);
  }

  const x = cx - w / 2;
  const y = cy - h / 2;

  const isHover = opts.hoverId === node.id;
  const inNbhd =
    opts.hoverId !== null &&
    opts.neighbourhood.get(opts.hoverId)?.has(node.id);
  const dimmed = opts.hoverId !== null && !inNbhd && !isHover;
  const isOrphan = node.degree === 0;

  // Base opacity chains: dim > back-layer > full.
  ctx.globalAlpha = dimmed ? 0.24 : isBack ? BACK_LAYER_ALPHA : 1;

  // Card background: near-opaque panel colour so the card reads as a
  // real UI card, not a ghost. A subtle node-colour tint sits on top
  // to preserve semantic colour, and a coloured header strip on top
  // of that gives strong hierarchy.
  if (isHover) {
    ctx.shadowColor = node.color;
    ctx.shadowBlur = 16;
  } else if (!isBack) {
    // Front cards get a soft drop-shadow so they visually pop above
    // the back plane. Back cards intentionally get no shadow.
    ctx.shadowColor = opts.isDark ? "rgba(0,0,0,0.60)" : "rgba(30,40,60,0.22)";
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 4;
  }
  // 1) Panel fill - a vertical gradient gives the card a brushed
  //    glass / stainless sheen instead of a flat pastel wash.
  const panel = ctx.createLinearGradient(0, y, 0, y + h);
  if (opts.isDark) {
    panel.addColorStop(0, "#2b323d");
    panel.addColorStop(0.5, "#212734");
    panel.addColorStop(1, "#161b24");
  } else {
    panel.addColorStop(0, "#ffffff");
    panel.addColorStop(0.5, "#f2f5f9");
    panel.addColorStop(1, "#e6eaf1");
  }
  ctx.fillStyle = panel;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
  // 2) Colour-glass overlay - a vertical tint gradient in the node's
  //    own hue turns the whole card into a solid coloured glass slab
  //    (lighter at the top like a glass highlight, deeper toward the
  //    bottom), instead of a near-white panel. This is what gives the
  //    card its "coloured glass slide" read in both themes.
  const tint = ctx.createLinearGradient(0, y, 0, y + h);
  if (opts.isDark) {
    tint.addColorStop(0, withAlpha(node.color, 0.2));
    tint.addColorStop(1, withAlpha(node.color, 0.38));
  } else {
    tint.addColorStop(0, withAlpha(node.color, 0.38));
    tint.addColorStop(1, withAlpha(node.color, 0.58));
  }
  ctx.fillStyle = tint;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  // 3) Glass gloss - a SINGLE global light source. The specular is a
  //    directional gradient pointing at one fixed light (lightDir is
  //    computed per card from its world position), so the highlights
  //    across all cards line up into one coherent reflection rather
  //    than an identical per-card stamp.
  const ld = opts.lightDir ?? { x: -0.6, y: -0.78 };
  ctx.save();
  roundedRect(ctx, x, y, w, h, 12);
  ctx.clip();
  const cxp = x + w / 2;
  const cyp = y + h / 2;
  const R = Math.max(w, h) * 0.78;
  // 3a) Directional sheen - bright on the light-facing side, fading
  //     across the slab.
  const spec = ctx.createLinearGradient(
    cxp + ld.x * R, cyp + ld.y * R,
    cxp - ld.x * R, cyp - ld.y * R,
  );
  spec.addColorStop(0, "rgba(255,255,255,0.22)");
  spec.addColorStop(0.3, "rgba(255,255,255,0.05)");
  spec.addColorStop(0.62, "rgba(255,255,255,0)");
  ctx.fillStyle = spec;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  // 3b) Glint - a soft hot-spot near the light-facing corner.
  const hx = cxp + ld.x * (w * 0.44);
  const hy = cyp + ld.y * (h * 0.44);
  const hot = ctx.createRadialGradient(hx, hy, 0, hx, hy, Math.min(w, h) * 0.55);
  hot.addColorStop(0, "rgba(255,255,255,0.18)");
  hot.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = hot;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  // 3c) Bottom underglow - a soft inner shadow that gives the slab depth.
  const underglow = ctx.createLinearGradient(0, y + h * 0.65, 0, y + h);
  underglow.addColorStop(0, "rgba(0,0,0,0)");
  underglow.addColorStop(1, opts.isDark ? "rgba(0,0,0,0.3)" : "rgba(30,40,60,0.12)");
  ctx.fillStyle = underglow;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  ctx.restore();

  // Border - strong metallic edge so cards separate cleanly against
  // the link ribbon behind them.
  ctx.lineWidth = isHover ? 2.6 : isBack ? 1.4 : 1.8;
  ctx.strokeStyle = isBack
    ? (opts.isDark ? withAlpha(node.color, 0.85) : shade(node.color, 0.72))
    : (opts.isDark ? withAlpha(node.color, 1) : shade(node.color, 0.62));
  if (isOrphan) ctx.setLineDash([3, 3]);
  roundedRect(ctx, x, y, w, h, 12);
  ctx.stroke();
  ctx.setLineDash([]);

  // Header strip - a saturated colour gradient so the type name reads
  // instantly and the card gains a strong top-down hierarchy.
  const headerH = HEADER_H;
  const header = ctx.createLinearGradient(0, y, 0, y + headerH);
  // Light mode uses a darkened ink of the hue so the white title clears
  // WCAG AA 4.5:1 (raw mid-tone hues gave white ~3.6:1). Dark mode keeps
  // the vivid strip since white already reads on the deep panel.
  header.addColorStop(0, opts.isDark ? withAlpha(node.color, 0.98) : shade(node.color, 0.82));
  header.addColorStop(1, opts.isDark ? withAlpha(node.color, 0.72) : shade(node.color, 0.6));
  ctx.fillStyle = header;
  roundedRectTop(ctx, x, y, w, headerH, 12);
  ctx.fill();
  // Header gloss - a bright band across the top of the strip so the
  //  header reads like a curved glass button catching the light.
  ctx.save();
  roundedRectTop(ctx, x, y, w, headerH, 12);
  ctx.clip();
  const headerGloss = ctx.createLinearGradient(0, y, 0, y + headerH);
  headerGloss.addColorStop(0, "rgba(255,255,255,0.32)");
  headerGloss.addColorStop(0.5, "rgba(255,255,255,0.06)");
  headerGloss.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = headerGloss;
  roundedRectTop(ctx, x, y, w, headerH, 12);
  ctx.fill();
  ctx.restore();

  // Header title. White on the saturated header strip for maximum
  // contrast, with a soft shadow so it stays legible on any hue.
  ctx.font =
    "700 14px 'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', sans-serif";
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.35)";
  ctx.shadowBlur = 2;
  ctx.shadowOffsetY = 0.5;
  const titleMax = w - 20;
  ctx.fillText(truncateText(ctx, node.name, titleMax), x + 10, y + headerH / 2);
  ctx.restore();

  // Body sections (properties / outgoing / incoming). Items over
  // MAX_ITEMS_PER_SECTION collapse into a single "+N more" line so
  // cards never grow taller than the grid row spacing.
  const bodyPadX = 9;
  const rowLabelFont =
    "600 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  const rowItemFont =
    "500 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  const contentMax = w - bodyPadX * 2;
  // Accessible accent: a darkened ink of the hue for the row icons and
  // count labels on a light card. The raw hue sat on a same-hue body at
  // ~3:1; shading it down to ~0.5 lifts small-text contrast past AA.
  const accentInk = opts.isDark ? node.color : shade(node.color, 0.5);

  const sections: readonly [string, string, readonly string[]][] = [
    ["P", `${node.propertyCount} properties`, node.properties],
    ["↑", `${node.outCount} outgoing`, node.outgoingLines],
    ["↓", `${node.inCount} incoming`, node.incomingLines],
  ];

  // Cursor walks down the card so variable section heights stack cleanly.
  let cursorY = y + headerH + BODY_PAD_Y;
  sections.forEach(([icon, header, items], sectionIdx) => {
    // Divider between sections: a subtle dashed line running across
    // the card so property / outgoing / incoming rows read as clearly
    // grouped blocks and the eye can jump to the row a link anchors to.
    if (sectionIdx > 0) {
      const dividerY = cursorY - Math.floor(SECTION_PAD / 2);
      ctx.save();
      ctx.strokeStyle = opts.isDark
        ? withAlpha(node.color, 0.35)
        : withAlpha(node.color, 0.25);
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x + bodyPadX, dividerY);
      ctx.lineTo(x + w - bodyPadX, dividerY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
    // Row header: coloured icon + count label.
    ctx.font = rowLabelFont;
    ctx.fillStyle = accentInk;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(icon, x + bodyPadX, cursorY);
    ctx.fillStyle = opts.isDark ? opts.mutedColor : accentInk;
    ctx.fillText(header, x + bodyPadX + 14, cursorY);

    // Row items: shown up to MAX_ITEMS_PER_SECTION, then a "+N more"
    // hint. Truncated horizontally to fit card width.
    ctx.font = rowItemFont;
    ctx.fillStyle = opts.labelColor;
    let lineY = cursorY + SECTION_LABEL_H;
    if (items.length === 0) {
      ctx.fillStyle = opts.mutedColor;
      ctx.fillText(icon === "P" ? "no properties" : "-", x + bodyPadX, lineY);
      lineY += ROW_H;
    } else {
      const shown = items.slice(0, MAX_ITEMS_PER_SECTION);
      for (const raw of shown) {
        const line = truncateText(ctx, raw, contentMax);
        ctx.fillText(line, x + bodyPadX, lineY);
        lineY += ROW_H;
      }
      const overflow = items.length - shown.length;
      if (overflow > 0) {
        ctx.fillStyle = opts.mutedColor;
        ctx.font = rowLabelFont;
        ctx.fillText(`+${overflow} more`, x + bodyPadX, lineY);
        ctx.font = rowItemFont;
        lineY += ROW_H;
      }
    }
    // Advance cursor by this section's reserved height (matches cardHeightFor()).
    const shownRows = Math.min(items.length, MAX_ITEMS_PER_SECTION);
    const overflowRow = items.length > MAX_ITEMS_PER_SECTION ? 1 : 0;
    const reservedRows = Math.max(1, shownRows + overflowRow);
    cursorY += SECTION_LABEL_H + reservedRows * ROW_H + SECTION_PAD;
  });

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Link label + link path + arrow
// ---------------------------------------------------------------------------

export function drawLinkLabel(
  ctx: CanvasRenderingContext2D,
  link: any,
  globalScale: number,
  opts: { readonly labelColor: string; readonly isDark: boolean },
) {
  const src = link.source;
  const tgt = link.target;
  if (typeof src === "string" || typeof tgt === "string") return;
  if (src.x === undefined || tgt.x === undefined) return;
  const inv = 1 / Math.max(0.6, globalScale);
  const midX = (src.x + tgt.x) / 2;
  const midY = (src.y + tgt.y) / 2;
  const fontSize = 10 * inv;
  ctx.font = `600 ${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  const label = link.label as string;
  const textW = ctx.measureText(label).width;
  const padX = 6 * inv;
  const w = textW + padX * 2;
  const h = fontSize + 6 * inv;
  const x = midX - w / 2;
  const y = midY - h / 2;
  ctx.fillStyle = opts.isDark ? "rgba(23,26,33,0.9)" : "rgba(255,255,255,0.94)";
  ctx.strokeStyle = link.color;
  ctx.lineWidth = 1 * inv;
  roundedRect(ctx, x, y, w, h, 6 * inv);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = opts.labelColor;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillText(label, midX, midY + 0.5);
}

/**
 * Draw a link that starts on the source card border, curves outward
 * from the canvas centre, and ends with an arrow tip on the target
 * card border. Text labels only appear for the hovered node's links
 * so the canvas does not become a wall of pill-labels.
 */
export function drawRectEdgeLink(
  ctx: CanvasRenderingContext2D,
  link: any,
  globalScale: number,
  opts: {
    readonly labelColor: string;
    readonly isDark: boolean;
    readonly hoverId: string | null;
  },
) {
  const src = link.source;
  const tgt = link.target;
  if (typeof src === "string" || typeof tgt === "string") return;
  if (src.x === undefined || tgt.x === undefined) return;
  // Per-node half-extents that already account for the back-layer
  // scale, so the arrow tip lands on the visible card edge.
  const hwSrc = nodeHalfW(src) + 4;
  const hhSrc = nodeHalfH(src) + 4;
  const hwTgt = nodeHalfW(tgt) + 4;
  const hhTgt = nodeHalfH(tgt) + 4;

  const involved =
    opts.hoverId !== null &&
    (src.id === opts.hoverId || tgt.id === opts.hoverId);
  const dim = opts.hoverId !== null && !involved;

  // Self-loop: draw a small arc above the card.
  if (src.id === tgt.id) {
    ctx.save();
    ctx.globalAlpha = dim ? 0.15 : 0.9;
    ctx.strokeStyle = involved ? "var(--accent, #4f9df5)" : link.color;
    ctx.lineWidth = involved ? 2.2 : 1.4;
    ctx.setLineDash(link.isCausal ? [] : [4, 4]);
    const cx = src.x;
    const cy = src.y;
    const rTop = cy - hhSrc;
    ctx.beginPath();
    ctx.moveTo(cx - 12, rTop);
    ctx.bezierCurveTo(cx - 12, rTop - 40, cx + 12, rTop - 40, cx + 12, rTop);
    ctx.stroke();
    ctx.setLineDash([]);
    // Arrow tip at the right side of the return leg.
    drawArrowHead(ctx, cx + 12, rTop, Math.PI / 2, involved ? 8 : 6);
    ctx.restore();
    return;
  }

  // Endpoint on each rectangle border along the line between centres.
  // Add a small curvature offset perpendicular to the segment so
  // parallel edges (multi-graph case) don't stack.
  const sx = src.x;
  const sy = src.y;
  const tx = tgt.x;
  const ty = tgt.y;
  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const nx = -dy / dist;
  const ny = dx / dist;
  const curveAmount = 12 + Math.min(28, dist * 0.05);
  const mx = (sx + tx) / 2 + nx * curveAmount;
  const my = (sy + ty) / 2 + ny * curveAmount;

  const start = rectBorderPoint(sx, sy, mx, my, hwSrc, hhSrc);
  const end = rectBorderPoint(tx, ty, mx, my, hwTgt, hhTgt);

  ctx.save();
  ctx.globalAlpha = dim ? 0.12 : 1;
  ctx.strokeStyle = involved ? "var(--accent, #4f9df5)" : link.color;
  ctx.lineWidth = involved ? 2.2 : 1.2;
  ctx.setLineDash(link.isCausal ? [] : [4, 4]);
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.quadraticCurveTo(mx, my, end.x, end.y);
  ctx.stroke();
  ctx.setLineDash([]);

  // Arrow head at the target-border point, pointing along the
  // tangent of the curve at t=1 (derivative of the quadratic bezier).
  const tanX = end.x - mx;
  const tanY = end.y - my;
  const tanAngle = Math.atan2(tanY, tanX);
  drawArrowHead(ctx, end.x, end.y, tanAngle, involved ? 9 : 7);

  ctx.restore();

  // Show the link label on the hovered node's edges.
  if (involved) {
    const inv = 1 / Math.max(0.6, globalScale);
    const fontSize = 10.5 * inv;
    ctx.font = `600 ${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
    const label = link.label as string;
    const textW = ctx.measureText(label).width;
    const padX = 6 * inv;
    const w = textW + padX * 2;
    const h = fontSize + 6 * inv;
    // Anchor label at the bezier midpoint (t=0.5).
    const lx = 0.25 * sx + 0.5 * mx + 0.25 * tx;
    const ly = 0.25 * sy + 0.5 * my + 0.25 * ty;
    ctx.fillStyle = opts.isDark ? "rgba(23,26,33,0.94)" : "rgba(255,255,255,0.96)";
    ctx.strokeStyle = link.color;
    ctx.lineWidth = 1;
    roundedRect(ctx, lx - w / 2, ly - h / 2, w, h, 6);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = opts.labelColor;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillText(label, lx, ly + 0.5);
  }
}

// ---------------------------------------------------------------------------
// Background: one-point-perspective floor grid
// ---------------------------------------------------------------------------

/**
 * Draw a subtle one-point-perspective floor grid onto the grid
 * underlay canvas.
 *
 * The grid is drawn in **screen coordinates** (origin at top-left,
 * (width, height) at bottom-right). The vanishing point sits above
 * the visible area so radial lines converge outside the canvas and
 * horizontal lines look like a floor receding into the distance.
 */
export function drawPerspectiveGrid(
  ctx: CanvasRenderingContext2D,
  opts: {
    readonly width: number;
    readonly height: number;
    readonly isDark: boolean;
    readonly globalScale: number;
  },
) {
  const { width: w, height: h, isDark } = opts;

  // Screen rectangle to fill with the grid.
  const left = 0;
  const top = 0;
  const right = w;
  const bottom = h;

  // Vanishing point sits ABOVE the canvas top edge so all radial
  // lines converge outside the visible rectangle - the grid feels
  // like a floor extending past the horizon.
  const vpX = w / 2;
  const vpY = top - h * 0.05;

  // Colours: two intensities so major grid lines pop more than the
  // fine grid. Kept subtle (max ~14% alpha) so they never fight the
  // cards for attention.
  const majorColor = isDark
    ? "rgba(180, 200, 230, 0.16)"
    : "rgba(80, 110, 160, 0.13)";
  const minorColor = isDark
    ? "rgba(150, 170, 200, 0.08)"
    : "rgba(80, 110, 160, 0.06)";

  ctx.save();
  ctx.lineWidth = 0.7;

  // Horizontal grid lines: perspective compression via a power curve,
  // so lines are dense near the horizon and sparse near the viewer.
  // rows = 12 gives a clear "floor tile" feel without being noisy.
  const rows = 12;
  const bandTop = top + h * 0.03; // start just below the visible top
  for (let i = 1; i <= rows; i++) {
    const t = i / rows;
    // Power > 1 pushes lines toward the horizon (small t values map
    // very close to vpY / top edge).
    const y = bandTop + (bottom - bandTop) * Math.pow(t, 2.0);
    ctx.strokeStyle = i % 4 === 0 ? majorColor : minorColor;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }

  // Radial grid lines: fan out from vanishing point down to the
  // bottom edge, extending slightly past the canvas horizontally so
  // no line stops abruptly at the edge.
  const cols = 14;
  const bottomL = left - w * 0.35;
  const bottomR = right + w * 0.35;
  for (let i = 0; i <= cols; i++) {
    const t = i / cols;
    const bx = bottomL + (bottomR - bottomL) * t;
    ctx.strokeStyle = i % 4 === 0 ? majorColor : minorColor;
    ctx.beginPath();
    ctx.moveTo(bx, bottom);
    ctx.lineTo(vpX, vpY);
    ctx.stroke();
  }

  // Horizon line - a slightly darker stripe along the top-most
  // horizontal line, so the eye reads a clear "far edge" of the
  // floor. This anchors the back-layer cards to a real horizon.
  const horizonY = bandTop + (bottom - bandTop) * Math.pow(1 / rows, 2.0);
  ctx.strokeStyle = isDark
    ? "rgba(200, 220, 255, 0.24)"
    : "rgba(60, 90, 140, 0.22)";
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  ctx.moveTo(left, horizonY);
  ctx.lineTo(right, horizonY);
  ctx.stroke();

  // Soft floor gradient: darker at the horizon, fading toward the
  // viewer. Reinforces the "receding into distance" cue without
  // adding hard lines.
  const grad = ctx.createLinearGradient(0, horizonY, 0, bottom);
  if (isDark) {
    grad.addColorStop(0, "rgba(80, 110, 160, 0.18)");
    grad.addColorStop(1, "rgba(80, 110, 160, 0)");
  } else {
    grad.addColorStop(0, "rgba(120, 140, 190, 0.11)");
    grad.addColorStop(1, "rgba(120, 140, 190, 0)");
  }
  ctx.fillStyle = grad;
  ctx.fillRect(left, horizonY, w, bottom - horizonY);

  ctx.restore();
}
