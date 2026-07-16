import type { OntologyEdge, OntologyNode } from "./ontology-graph.types";

export interface OntologyRelation {
  readonly edges: readonly OntologyEdge[];
  readonly node: OntologyNode;
}

export interface OntologyNeighborhood {
  readonly focus: OntologyNode | null;
  readonly incoming: readonly OntologyRelation[];
  readonly outgoing: readonly OntologyRelation[];
  readonly selfLinks: readonly OntologyEdge[];
  readonly nodeNames: ReadonlySet<string>;
}

const relationOrder = (left: OntologyRelation, right: OntologyRelation): number =>
  left.node.name.localeCompare(right.node.name);

export function buildOntologyNeighborhood(
  nodes: readonly OntologyNode[],
  edges: readonly OntologyEdge[],
  requestedName: string | null,
): OntologyNeighborhood {
  const focus = nodes.find((node) => node.name === requestedName) ?? nodes[0] ?? null;
  if (!focus) {
    return {
      focus: null,
      incoming: [],
      outgoing: [],
      selfLinks: [],
      nodeNames: new Set(),
    };
  }

  const nodesByName = new Map(nodes.map((node) => [node.name, node]));
  const incomingByName = new Map<string, { node: OntologyNode; edges: OntologyEdge[] }>();
  const outgoingByName = new Map<string, { node: OntologyNode; edges: OntologyEdge[] }>();
  const selfLinks: OntologyEdge[] = [];
  const nodeNames = new Set([focus.name]);

  for (const edge of edges) {
    if (edge.from_type === focus.name && edge.to_type === focus.name) {
      selfLinks.push(edge);
      continue;
    }
    if (edge.to_type === focus.name) {
      const node = nodesByName.get(edge.from_type);
      if (node) {
        const relation = incomingByName.get(node.name) ?? { node, edges: [] };
        relation.edges.push(edge);
        incomingByName.set(node.name, relation);
        nodeNames.add(node.name);
      }
    }
    if (edge.from_type === focus.name) {
      const node = nodesByName.get(edge.to_type);
      if (node) {
        const relation = outgoingByName.get(node.name) ?? { node, edges: [] };
        relation.edges.push(edge);
        outgoingByName.set(node.name, relation);
        nodeNames.add(node.name);
      }
    }
  }

  const incoming = [...incomingByName.values()];
  const outgoing = [...outgoingByName.values()];
  for (const relation of [...incoming, ...outgoing]) {
    relation.edges.sort((left, right) => left.name.localeCompare(right.name));
  }
  incoming.sort(relationOrder);
  outgoing.sort(relationOrder);
  selfLinks.sort((left, right) => left.name.localeCompare(right.name));

  return { focus, incoming, outgoing, selfLinks, nodeNames };
}
