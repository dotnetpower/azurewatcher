import { useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  PageHeader,
  UnavailableState,
  type AsyncState,
} from "../components/ui";
import { MermaidDiagram } from "../components/mermaid-diagram";
import {
  OntologyGraph,
  type OntologyEdge,
  type OntologyNode,
} from "../components/ontology-graph";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { OntologyActionsView } from "./ontology-actions";
import { OntologyLinksView } from "./ontology-links";
import {
  ontologyView,
  type OntologyGraphResponse,
  type OntologyView,
} from "./ontology.types";

/**
 * Ontology explorer panel. ObjectTypes render as a one-hop graph,
 * LinkTypes as endpoint contracts, and ActionTypes as safety contracts.
 */

interface Props {
  readonly client: ReadApiClient;
}

export function OntologyRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<OntologyGraphResponse>>({ status: "loading" });
  const [includeProperties, setIncludeProperties] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = await client.panel<OntologyGraphResponse>(
          "/ontology/graph",
          { include_properties: includeProperties ? "true" : "false" },
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message:
                "The ontology explorer route is not wired on this deployment. " +
                "Set ReadApiConfig.ontology_object_types + ontology_link_types " +
                "in the composition root to enable it.",
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, includeProperties]);

  return (
    <div class="stack governance-route ontology-route">
      <PageHeader
        title={t("route.ontology")}
        subtitle="Browse ObjectTypes, LinkTypes, and the ActionType safety contracts registered on this deployment."
      />
      <AsyncBoundary state={state} resourceLabel="ontology graph">
        {(data) => (
          <OntologyBody
            data={data}
            includeProperties={includeProperties}
            onIncludePropertiesChange={setIncludeProperties}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function OntologyBody({
  data,
  includeProperties,
  onIncludePropertiesChange,
}: {
  readonly data: OntologyGraphResponse;
  readonly includeProperties: boolean;
  readonly onIncludePropertiesChange: (value: boolean) => void;
}) {
  const initialName = useMemo(() => {
    const requested = new URLSearchParams(window.location.search).get("type");
    if (requested && data.nodes?.some((node) => node.name === requested)) return requested;
    if (requested) return null;
    return data.nodes?.[0]?.name ?? null;
  }, [data.nodes]);
  const [selectedName, setSelectedName] = useState<string | null>(initialName);
  const [view, setView] = useState<OntologyView>(() => ontologyView(currentRoute().search.get("view")));
  const [selectedLink, setSelectedLink] = useState<string | null>(() => {
    const requested = currentRoute().search.get("link");
    return requested && data.link_types.includes(requested) ? requested : data.link_types[0] ?? null;
  });
  const actionTypes = data.action_types ?? [];
  const [selectedAction, setSelectedAction] = useState<string | null>(() => {
    const requested = currentRoute().search.get("action");
    return requested && actionTypes.some((action) => action.name === requested)
      ? requested
      : actionTypes[0]?.name ?? null;
  });
  const [invalidName, setInvalidName] = useState<string | null>(() => {
    const requested = currentRoute().search.get("type");
    return requested && !data.nodes?.some((node) => node.name === requested) ? requested : null;
  });
  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const requested = route.search.get("type");
      const valid = requested && data.nodes?.some((node) => node.name === requested);
      setInvalidName(requested && !valid ? requested : null);
      setSelectedName(valid ? requested : requested ? null : data.nodes?.[0]?.name ?? null);
      setView(ontologyView(route.search.get("view")));
      const link = route.search.get("link");
      setSelectedLink(link && data.link_types.includes(link) ? link : data.link_types[0] ?? null);
      const action = route.search.get("action");
      setSelectedAction(
        action && actionTypes.some((item) => item.name === action)
          ? action
          : actionTypes[0]?.name ?? null,
      );
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [actionTypes, data.link_types, data.nodes]);
  const selectType = (name: string | null): void => {
    navigate(routeHref("ontology", { params: { view: "objects", type: name } }));
  };
  usePublishViewContext(
    () => {
      // Ground the deck in the rendered graph, not just the two counts:
      // each ObjectType with its property count + description, and every
      // relationship (LinkType edge) with its from/to types and cardinality
      // so "what is X / what does X connect to?" is answerable. Structured
      // nodes/edges are absent on old servers - fall back to bare names.
      const objectTypeRecords =
        data.nodes && data.nodes.length > 0
          ? data.nodes.map((n) => ({
              name: n.name,
              properties: n.property_count,
              description: n.description ?? "-",
            }))
          : data.object_types.map((name) => ({ name }));
      const relationshipRecords =
        data.edges && data.edges.length > 0
          ? data.edges.map((e) => ({
              link: e.name,
              from: e.from_type,
              to: e.to_type,
              cardinality: e.cardinality,
              causal: e.is_causal,
              description: e.description ?? "-",
            }))
          : data.link_types.map((name) => ({ name }));
      return {
        routeId: "ontology",
        routeLabel: "Ontology",
        purpose:
          "The registered ObjectTypes and LinkTypes - the typed vocabulary the " +
          "control plane reasons over (resources, actions, and the causal links " +
          "between them). Read-only reference.",
        glossary: composeGlossary([TERMS.actionType, TERMS.blastRadius]),
        headline: `${data.object_type_count} ObjectTypes - ${data.link_type_count} LinkTypes - ${data.action_type_count ?? actionTypes.length} ActionTypes`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "object_type_count", value: data.object_type_count, group: "graph" },
          { key: "link_type_count", value: data.link_type_count, group: "graph" },
          { key: "action_type_count", value: data.action_type_count ?? actionTypes.length, group: "catalog" },
        ],
        records: {
          object_types: objectTypeRecords,
          relationships: relationshipRecords,
          action_types: actionTypes.map((action) => ({
            name: action.name,
            operation: action.operation,
            category: action.category ?? "-",
            trigger: String(action.trigger_kind?.kind ?? "-"),
            execution_path: action.execution_path ?? "-",
            rollback_contract: action.rollback_contract,
            default_mode: action.default_mode,
            irreversible: action.irreversible,
            description: action.description ?? "-",
          })),
        },
      };
    },
    [actionTypes, data],
  );
  return (
    <div class="stack governance-ontology">
      <nav class="ontology-tabs" aria-label="Ontology registry views">
        <OntologyTab view="objects" active={view} count={data.object_type_count} label="Objects" />
        <OntologyTab view="links" active={view} count={data.link_type_count} label="Links" />
        <OntologyTab view="actions" active={view} count={data.action_type_count ?? actionTypes.length} label="Actions" />
      </nav>

      {view === "objects" ? (
        <>
          <div class="ontology-object-toolbar">
            <span>One-hop ObjectType neighborhood</span>
            <label class="inline-toggle">
              <input
                type="checkbox"
                checked={includeProperties}
                onChange={(event) => onIncludePropertiesChange((event.target as HTMLInputElement).checked)}
              />
              show properties
            </label>
          </div>
          <div class="ontology-browser-layout">
            <aside class="ontology-type-sidebar">
              <TypeSelector
                title="ObjectTypes"
                names={data.object_types}
                selected={selectedName}
                onSelect={selectType}
              />
            </aside>
            <section class="ontology-neighborhood">
              <header>
                <div>
                  <h3>Neighborhood of <code>{selectedName ?? "ontology"}</code></h3>
                  <p>Select a neighboring card to move through the one-hop graph. Hover or focus a card to inspect its properties.</p>
                </div>
              </header>
              {invalidName ? (
                <UnavailableState message={`ObjectType ${invalidName} is not registered. Choose a type from the directory.`} />
              ) : data.nodes && data.edges ? (
                <OntologyGraph
                  key={selectedName ?? "default"}
                  nodes={data.nodes}
                  edges={data.edges}
                  initialName={selectedName}
                  onFocusChange={selectType}
                  onLinkSelect={(name) => navigate(routeHref("ontology", { params: { view: "links", link: name } }))}
                />
              ) : (
                <MermaidDiagram source={data.mermaid} ariaLabel="Ontology class diagram" />
              )}
            </section>
          </div>
          <details class="mermaid-source-toggle governance-source-details">
            <summary class="details-summary">Show deterministic Mermaid source</summary>
            <pre class="mono scroll code-block">{data.mermaid}</pre>
          </details>
        </>
      ) : null}

      {view === "links" ? (
        <OntologyLinksView
          names={data.link_types}
          nodes={data.nodes ?? []}
          edges={data.edges ?? []}
          selectedName={selectedLink}
        />
      ) : null}

      {view === "actions" ? (
        <OntologyActionsView actions={actionTypes} selectedName={selectedAction} />
      ) : null}
    </div>
  );
}

function OntologyTab({
  view,
  active,
  count,
  label,
}: {
  readonly view: OntologyView;
  readonly active: OntologyView;
  readonly count: number;
  readonly label: string;
}) {
  return (
    <a
      href={routeHref("ontology", { params: { view } })}
      class={view === active ? "is-active" : undefined}
      aria-current={view === active ? "page" : undefined}
    >
      <span>{label}</span>
      <strong>{count}</strong>
    </a>
  );
}

function TypeSelector({
  title,
  names,
  selected,
  onSelect,
}: {
  readonly title: string;
  readonly names: readonly string[];
  readonly selected: string | null;
  readonly onSelect?: (name: string) => void;
}) {
  return (
    <section>
      <h3>{title} <span>{names.length}</span></h3>
      {names.length === 0 ? <p class="muted">None registered.</p> : (
        <ul>
          {names.map((name) => (
            <li key={name}>
              {onSelect ? (
                <button
                  type="button"
                  class={selected === name ? "is-active" : undefined}
                  onClick={() => onSelect(name)}
                >
                  <code>{name}</code>
                </button>
              ) : <code>{name}</code>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
