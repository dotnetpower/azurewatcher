import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import { routeHref } from "../router";

export function OntologyLinksView({
  names,
  nodes,
  edges,
  selectedName,
}: {
  readonly names: readonly string[];
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly selectedName: string | null;
}) {
  const selectedEdges = edges.filter((edge) => edge.name === selectedName);
  const selected = selectedEdges[0] ?? null;
  const nodesByName = new Map(nodes.map((node) => [node.name, node]));

  return (
    <div class="ontology-browser-layout ontology-links-view">
      <aside class="ontology-type-sidebar">
        <section>
          <h3>LinkTypes <span>{names.length}</span></h3>
          {names.length === 0 ? <p class="muted">None registered.</p> : (
            <ul>
              {names.map((name) => (
                <li key={name}>
                  <a
                    href={routeHref("ontology", { params: { view: "links", link: name } })}
                    class={name === selectedName ? "is-active" : undefined}
                    aria-current={name === selectedName ? "page" : undefined}
                  >
                    <span class="ontology-link-glyph" aria-hidden="true" />
                    <code>{name}</code>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>

      <section class="ontology-link-stage">
        {selected ? (
          <>
            <header class="ontology-view-head">
              <div>
                <span class="eyebrow">LinkType</span>
                <h3><code>{selected.name}</code></h3>
                <p>{selected.description ?? "No description is recorded for this LinkType."}</p>
              </div>
              <span class="badge">{selectedEdges.length} usage{selectedEdges.length === 1 ? "" : "s"}</span>
            </header>

            <div class="ontology-link-workspace">
              <div class="ontology-link-usages" aria-label={`${selected.name} endpoint usages`}>
                {selectedEdges.map((edge, index) => (
                  <article class="ontology-link-usage" key={`${edge.from_type}-${edge.to_type}-${index}`}>
                    <a
                      class="ontology-endpoint"
                      href={routeHref("ontology", { params: { view: "objects", type: edge.from_type } })}
                    >
                      <span>From ObjectType</span>
                      <strong>{edge.from_type}</strong>
                      <small>{nodesByName.get(edge.from_type)?.description ?? "Open object neighborhood"}</small>
                    </a>
                    <div class="ontology-link-signature" aria-label={`${edge.name} ${edge.cardinality}`}>
                      <span>{edge.cardinality}</span>
                      <strong>{edge.name}</strong>
                      <i aria-hidden="true">→</i>
                    </div>
                    <a
                      class="ontology-endpoint"
                      href={routeHref("ontology", { params: { view: "objects", type: edge.to_type } })}
                    >
                      <span>To ObjectType</span>
                      <strong>{edge.to_type}</strong>
                      <small>{nodesByName.get(edge.to_type)?.description ?? "Open object neighborhood"}</small>
                    </a>
                  </article>
                ))}
              </div>

              <aside class="ontology-link-inspector" aria-label="LinkType properties">
                <h4>Relationship contract</h4>
                <dl>
                  <dt>Cardinality</dt><dd><code>{selected.cardinality}</code></dd>
                  <dt>Causal</dt><dd>{selected.is_causal ? "Yes" : "No"}</dd>
                  <dt>Transitive</dt><dd>{selected.is_transitive ? "Yes" : "No"}</dd>
                  <dt>Temporal order</dt><dd>{selected.temporal_order ? "Yes" : "No"}</dd>
                  <dt>Endpoint pairs</dt><dd>{selectedEdges.length}</dd>
                </dl>
                <h4>Used by</h4>
                <ul>
                  {selectedEdges.map((edge, index) => (
                    <li key={`${edge.from_type}-${edge.to_type}-${index}`}>
                      <code>{edge.from_type}</code>
                      <span>→</span>
                      <code>{edge.to_type}</code>
                    </li>
                  ))}
                </ul>
              </aside>
            </div>
          </>
        ) : (
          <div class="empty-state">Choose a LinkType to inspect its endpoint contract.</div>
        )}
      </section>
    </div>
  );
}
