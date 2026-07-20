import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import type { ElkEdgeSection, ElkPoint } from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "../layout/elk.js";
import type {
  DiagramEdge,
  DiagramNode,
  DiagramSpec,
  EdgeKind,
  Locale,
} from "../model/types.js";

const edgeStyles: Record<EdgeKind, { color: string; dash: string; width: number }> = {
  request: { color: "#2563eb", dash: "none", width: 2.4 },
  event: { color: "#0078d4", dash: "7 4", width: 2.4 },
  approval: { color: "#8b5cf6", dash: "3 4", width: 2.6 },
  mutation: { color: "#d83b01", dash: "none", width: 3 },
  audit: { color: "#107c10", dash: "2 4", width: 2.4 },
  rollback: { color: "#a4262c", dash: "9 4 2 4", width: 2.6 },
  read: { color: "#008272", dash: "5 4", width: 2.2 },
  write: { color: "#5c2d91", dash: "none", width: 2.6 },
};

interface IconLock {
  icons: Record<string, { file: string; productName: string; sha256: string }>;
}

const iconDirectory = fileURLToPath(
  new URL("../../assets/azure/", import.meta.url),
);
const iconLock = JSON.parse(
  await readFile(new URL("../../assets/azure/icons.lock.json", import.meta.url), "utf8"),
) as IconLock;

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function splitLabel(value: string, limit = 20): string[] {
  const words = value.split(/\s+/u);
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= limit || !current) current = candidate;
    else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, 3);
}

function textLines(
  lines: string[],
  x: number,
  startY: number,
  className: string,
): string {
  return `<text class="${className}" x="${x}" y="${startY}" text-anchor="middle">${lines
    .map(
      (line, index) =>
        `<tspan x="${x}" dy="${index === 0 ? 0 : 18}">${escapeXml(line)}</tspan>`,
    )
    .join("")}</text>`;
}

async function iconDataUri(icon: string | undefined): Promise<string | undefined> {
  if (!icon) return undefined;
  const entry = iconLock.icons[icon];
  if (!entry) throw new Error(`Unknown diagram icon '${icon}'`);
  const source = await readFile(`${iconDirectory}/${entry.file}`);
  const digest = createHash("sha256").update(source).digest("hex");
  if (digest !== entry.sha256) {
    throw new Error(`Diagram icon '${icon}' does not match icons.lock.json`);
  }
  return `data:image/svg+xml;base64,${source.toString("base64")}`;
}

function genericIcon(node: DiagramNode, shape: PositionedShape): string {
  const x = shape.x + shape.width / 2;
  const y = shape.y + 38;
  const abbreviation = node.label.en
    .split(/\s+/u)
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  if (node.kind === "store") {
    return `<g class="generic-icon" aria-hidden="true"><ellipse cx="${x}" cy="${y - 10}" rx="19" ry="7"/><path d="M${x - 19} ${y - 10}v22c0 4 9 7 19 7s19-3 19-7v-22"/><path d="M${x - 19} ${y}c0 4 9 7 19 7s19-3 19-7"/></g>`;
  }
  if (node.kind === "decision") {
    return `<g class="generic-icon" aria-hidden="true"><path d="M${x} ${y - 24}l24 24-24 24-24-24z"/><text x="${x}" y="${y + 5}" text-anchor="middle">${escapeXml(abbreviation)}</text></g>`;
  }
  return `<g class="generic-icon" aria-hidden="true"><circle cx="${x}" cy="${y}" r="24"/><text x="${x}" y="${y + 5}" text-anchor="middle">${escapeXml(abbreviation)}</text></g>`;
}

async function renderNode(
  node: DiagramNode,
  shape: PositionedShape,
  locale: Locale,
): Promise<string> {
  const icon = await iconDataUri(node.icon);
  const x = shape.x + shape.width / 2;
  const labelLines = splitLabel(node.label[locale]);
  const labelStart = shape.y + shape.height - 28 - (labelLines.length - 1) * 9;
  const iconMarkup = icon
    ? `<image href="${icon}" x="${x - 25}" y="${shape.y + 13}" width="50" height="50" preserveAspectRatio="xMidYMid meet" aria-hidden="true"/>`
    : genericIcon(node, shape);
  const description = node.description?.[locale] ?? node.label[locale];
  return `<g class="diagram-node node-${node.kind}" data-node-id="${node.id}" role="button" tabindex="0" aria-label="${escapeXml(`${node.label[locale]}. ${description}`)}"><rect x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" rx="8"/>${iconMarkup}${textLines(labelLines, x, labelStart, "node-label")}</g>`;
}

function edgePath(points: ElkPoint[], offsetX: number, offsetY: number): string {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x + offsetX} ${point.y + offsetY}`)
    .join(" ");
}

function sectionPoints(section: ElkEdgeSection): ElkPoint[] {
  return [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
}

function edgeLabelPosition(section: ElkEdgeSection): ElkPoint {
  const points = sectionPoints(section);
  const middle = Math.max(0, Math.floor((points.length - 1) / 2));
  const first = points[middle] ?? section.startPoint;
  const second = points[middle + 1] ?? section.endPoint;
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
}

function renderEdge(
  edge: DiagramEdge,
  section: ElkEdgeSection,
  locale: Locale,
  offsetX: number,
  offsetY: number,
): string {
  const style = edgeStyles[edge.kind];
  const position = edgeLabelPosition(section);
  const label = edge.label?.[locale];
  const labelMarkup = label
    ? `<g class="edge-label" transform="translate(${position.x + offsetX} ${position.y + offsetY - 9})"><rect x="${-Math.max(30, label.length * 4.3)}" y="-12" width="${Math.max(60, label.length * 8.6)}" height="24" rx="4"/><text text-anchor="middle" y="4">${escapeXml(label)}</text></g>`
    : "";
  return `<g class="diagram-edge edge-${edge.kind}" data-edge-id="${edge.id}" data-edge-from="${edge.from.split(":", 1)[0]}" data-edge-to="${edge.to.split(":", 1)[0]}"><path d="${edgePath(sectionPoints(section), offsetX, offsetY)}" fill="none" stroke="${style.color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" marker-end="url(#arrow-${edge.kind})"/>${labelMarkup}</g>`;
}

function renderLegend(spec: DiagramSpec, locale: Locale, y: number): string {
  if (!spec.legend?.length) return "";
  let x = 48;
  const items = spec.legend.map((item) => {
    const style = edgeStyles[item.kind];
    const label = item.label[locale];
    const width = Math.max(120, label.length * 9 + 58);
    const markup = `<g class="legend-item" transform="translate(${x} ${y})"><line x1="0" y1="0" x2="34" y2="0" stroke="${style.color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" marker-end="url(#arrow-${item.kind})"/><text x="45" y="5">${escapeXml(label)}</text></g>`;
    x += width;
    return markup;
  });
  return `<g class="diagram-legend" aria-label="Legend">${items.join("")}</g>`;
}

export async function renderSvg(
  spec: DiagramSpec,
  layout: DiagramLayout,
  locale: Locale,
): Promise<string> {
  const offsetX = 48;
  const offsetY = 112;
  const legendHeight = spec.legend?.length ? 58 : 20;
  const width = Math.max(spec.canvas.width, Math.ceil(layout.width + offsetX * 2));
  const height = Math.max(
    spec.canvas.height,
    Math.ceil(layout.height + offsetY + legendHeight),
  );
  const groupById = new Map(spec.groups.map((group) => [group.id, group]));
  const nodeById = new Map(spec.nodes.map((node) => [node.id, node]));
  const edgeById = new Map(spec.edges.map((edge) => [edge.id, edge]));
  const markers = Object.entries(edgeStyles)
    .map(
      ([kind, style]) =>
        `<marker id="arrow-${kind}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${style.color}"/></marker>`,
    )
    .join("");
  const groups = [...layout.groups.values()]
    .sort((left, right) => left.depth - right.depth)
    .map((shape) => {
      const group = groupById.get(shape.id);
      if (!group) return "";
      return `<g class="diagram-group group-${group.kind}" data-group-id="${group.id}"><rect x="${shape.x + offsetX}" y="${shape.y + offsetY}" width="${shape.width}" height="${shape.height}" rx="8"/><text x="${shape.x + offsetX + 18}" y="${shape.y + offsetY + 29}">${escapeXml(group.label[locale])}</text></g>`;
    })
    .join("");
  const edges = layout.edges
    .flatMap((layoutEdge) => {
      const edge = edgeById.get(layoutEdge.id);
      if (!edge) return [];
      return (layoutEdge.sections ?? []).map((section) =>
        renderEdge(edge, section, locale, offsetX, offsetY),
      );
    })
    .join("");
  const nodes = (
    await Promise.all(
      [...layout.nodes.values()].map(async (shape) => {
        const node = nodeById.get(shape.id);
        if (!node) return "";
        const translatedShape = {
          ...shape,
          x: shape.x + offsetX,
          y: shape.y + offsetY,
        };
        return renderNode(node, translatedShape, locale);
      }),
    )
  ).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="diagram-title diagram-description" data-diagram-id="${spec.id}" data-locale="${locale}">
  <title id="diagram-title">${escapeXml(spec.locales[locale].title)}</title>
  <desc id="diagram-description">${escapeXml(spec.locales[locale].alt)}</desc>
  <metadata>${escapeXml(JSON.stringify({ id: spec.id, version: spec.version, updated: spec.updated }))}</metadata>
  <defs>${markers}<filter id="node-shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#172b4d" flood-opacity="0.14"/></filter></defs>
  <style>
    svg { color: #172b4d; font-family: "Noto Sans KR", "Noto Sans", "Segoe UI", sans-serif; }
    .diagram-title { font-size: 26px; font-weight: 700; fill: #172b4d; }
    .diagram-subtitle { font-size: 14px; fill: #526581; }
    .diagram-group rect { fill: #ffffff; stroke: #9db3ce; stroke-width: 1.5; stroke-dasharray: 5 4; }
    .diagram-group.group-system rect, .diagram-group.group-layer rect { fill: #edf6ff; stroke: #0078d4; }
    .diagram-group.group-network rect, .diagram-group.group-subnet rect { fill: #f3fbf8; stroke: #008272; }
    .diagram-group text { font-size: 14px; font-weight: 650; fill: #2d4260; }
    .diagram-node rect { fill: #ffffff; stroke: #8da3bf; stroke-width: 1.25; filter: url(#node-shadow); }
    .diagram-node:hover rect, .diagram-node:focus rect, .diagram-node.is-active rect { stroke: #0078d4; stroke-width: 3; }
    .diagram-node:focus { outline: none; }
    .node-label { font-size: 13px; font-weight: 650; fill: #172b4d; letter-spacing: 0; }
    .generic-icon circle, .generic-icon path { fill: #e5f1fb; stroke: #0078d4; stroke-width: 1.8; }
    .generic-icon text { font-size: 12px; font-weight: 700; fill: #005a9e; }
    .edge-label rect { fill: #ffffff; stroke: #d6e0ec; }
    .edge-label text, .legend-item text { font-size: 12px; font-weight: 600; fill: #334a68; }
    .diagram-edge.is-muted { opacity: 0.12; }
    .diagram-edge.is-active path { stroke-width: 4; }
  </style>
  <rect class="diagram-background" width="${width}" height="${height}" fill="#f7f9fc"/>
  <text class="diagram-title" x="48" y="45">${escapeXml(spec.locales[locale].title)}</text>
  <text class="diagram-subtitle" x="48" y="72">${escapeXml(spec.locales[locale].description)}</text>
  <g data-diagram-viewport="">${groups}${edges}${nodes}${renderLegend(spec, locale, height - 30)}</g>
</svg>`;
}
