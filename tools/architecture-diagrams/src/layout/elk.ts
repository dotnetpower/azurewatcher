import type {
  ElkExtendedEdge,
  ElkNode,
  ElkPort,
} from "elkjs/lib/elk-api.js";
import { createRequire } from "node:module";

import type {
  DiagramGroup,
  DiagramNode,
  DiagramSpec,
} from "../model/types.js";

export interface PositionedShape {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
}

export interface DiagramLayout {
  width: number;
  height: number;
  groups: Map<string, PositionedShape>;
  nodes: Map<string, PositionedShape>;
  edges: ElkExtendedEdge[];
}

const require = createRequire(import.meta.url);
const ElkConstructor = require("elkjs/lib/elk.bundled.js") as typeof import("elkjs/lib/elk-api.js").default;
const elk = new ElkConstructor();

function nodePorts(node: DiagramNode): ElkPort[] | undefined {
  if (!node.ports?.length) return undefined;
  return node.ports.map((port) => ({
    id: `${node.id}:${port.id}`,
    width: 1,
    height: 1,
    layoutOptions: {
      "elk.port.side": port.side,
    },
  }));
}

function diagramNodeToElk(node: DiagramNode): ElkNode {
  const ports = nodePorts(node);
  return {
    id: node.id,
    width: node.width ?? 164,
    height: node.height ?? 104,
    ...(ports ? { ports } : {}),
    ...(ports
      ? { layoutOptions: { "elk.portConstraints": "FIXED_SIDE" } }
      : {}),
  };
}

function childrenForGroup(spec: DiagramSpec, group: DiagramGroup): ElkNode[] {
  const childGroups = spec.groups
    .filter((candidate) => candidate.parent === group.id)
    .map((candidate) => groupToElk(spec, candidate));
  const childNodes = spec.nodes
    .filter((node) => node.parent === group.id)
    .map(diagramNodeToElk);
  return [...childGroups, ...childNodes];
}

function groupToElk(spec: DiagramSpec, group: DiagramGroup): ElkNode {
  return {
    id: group.id,
    children: childrenForGroup(spec, group),
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": group.direction ?? spec.canvas.direction,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.padding": "[top=52,left=28,bottom=28,right=28]",
      "elk.spacing.nodeNode": "28",
      "elk.layered.spacing.nodeNodeBetweenLayers": "48",
    },
  };
}

function collectShapes(
  node: ElkNode,
  groupIds: Set<string>,
  parentX: number,
  parentY: number,
  depth: number,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): void {
  const x = parentX + (node.x ?? 0);
  const y = parentY + (node.y ?? 0);
  if (node.id !== "root") {
    const shape = {
      id: node.id,
      x,
      y,
      width: node.width ?? 0,
      height: node.height ?? 0,
      depth,
    };
    if (groupIds.has(node.id)) groups.set(node.id, shape);
    else nodes.set(node.id, shape);
  }
  for (const child of node.children ?? []) {
    collectShapes(child, groupIds, x, y, depth + 1, groups, nodes);
  }
}

export async function layoutDiagram(spec: DiagramSpec): Promise<DiagramLayout> {
  const rootGroups = spec.groups
    .filter((group) => !group.parent)
    .map((group) => groupToElk(spec, group));
  const rootNodes = spec.nodes
    .filter((node) => !node.parent)
    .map(diagramNodeToElk);
  const graph: ElkNode = {
    id: "root",
    children: [...rootGroups, ...rootNodes],
    edges: spec.edges.map((edge) => ({
      id: edge.id,
      sources: [edge.from],
      targets: [edge.to],
    })),
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": spec.canvas.direction,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.padding": `[top=${spec.canvas.padding ?? 40},left=${spec.canvas.padding ?? 40},bottom=${spec.canvas.padding ?? 40},right=${spec.canvas.padding ?? 40}]`,
      "elk.spacing.nodeNode": "36",
      "elk.layered.spacing.nodeNodeBetweenLayers": "72",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
  };

  const result = await elk.layout(graph);
  const groups = new Map<string, PositionedShape>();
  const nodes = new Map<string, PositionedShape>();
  collectShapes(
    result,
    new Set(spec.groups.map((group) => group.id)),
    0,
    0,
    0,
    groups,
    nodes,
  );

  return {
    width: result.width ?? spec.canvas.width,
    height: result.height ?? spec.canvas.height,
    groups,
    nodes,
    edges: result.edges ?? [],
  };
}
