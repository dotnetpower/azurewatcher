import { useState } from "preact/hooks";
import { routeHref } from "../router";
import {
  compactRecord,
  formatUnknown,
  recordValue,
  type OntologyActionTypeRecord,
  type UnknownRecord,
} from "./ontology.types";

const ALL = "all";

export function OntologyActionsView({
  actions,
  selectedName,
}: {
  readonly actions: readonly OntologyActionTypeRecord[];
  readonly selectedName: string | null;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(ALL);
  const [trigger, setTrigger] = useState(ALL);
  const [execution, setExecution] = useState(ALL);
  const normalizedQuery = query.trim().toLowerCase();
  const categories = uniqueValues(actions.map((action) => action.category));
  const triggers = uniqueValues(actions.map((action) => recordValue(action.trigger_kind, "kind")));
  const executions = uniqueValues(actions.map((action) => action.execution_path));
  const filtered = actions.filter((action) => {
    const matchesQuery = normalizedQuery === ""
      || action.name.toLowerCase().includes(normalizedQuery)
      || (action.description ?? "").toLowerCase().includes(normalizedQuery)
      || action.operation.toLowerCase().includes(normalizedQuery);
    return matchesQuery
      && (category === ALL || action.category === category)
      && (trigger === ALL || recordValue(action.trigger_kind, "kind") === trigger)
      && (execution === ALL || action.execution_path === execution);
  });
  const requested = actions.find((action) => action.name === selectedName) ?? null;
  const selected = requested && filtered.includes(requested) ? requested : filtered[0] ?? null;

  if (actions.length === 0) {
    return <div class="empty-state">ActionType projection is unavailable on this deployment.</div>;
  }

  return (
    <section class="ontology-actions-view">
      <div class="ontology-action-toolbar">
        <label class="ontology-action-search">
          <span>Search</span>
          <input
            type="search"
            value={query}
            placeholder="ActionType name or operation"
            onInput={(event) => setQuery((event.target as HTMLInputElement).value)}
          />
        </label>
        <ActionFilter label="Category" value={category} values={categories} onChange={setCategory} />
        <ActionFilter label="Trigger" value={trigger} values={triggers} onChange={setTrigger} />
        <ActionFilter label="Execution" value={execution} values={executions} onChange={setExecution} />
        <span class="ontology-action-result-count">{filtered.length} of {actions.length}</span>
      </div>

      <div class="ontology-action-workspace">
        <div class="ontology-action-table-wrap">
          <table class="ontology-action-table">
            <thead>
              <tr>
                <th>ActionType</th>
                <th>Category</th>
                <th>Trigger</th>
                <th>Execution</th>
                <th>Rollback</th>
                <th>Default</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((action) => (
                <tr key={action.name} class={action.name === selected?.name ? "is-selected" : undefined}>
                  <td>
                    <a
                      href={routeHref("ontology", { params: { view: "actions", action: action.name } })}
                      aria-current={action.name === selected?.name ? "page" : undefined}
                    >
                      <code>{action.name}</code>
                      <small>{action.description ?? action.operation}</small>
                    </a>
                  </td>
                  <td><span class={`ontology-action-category is-${action.category ?? "other"}`}>{action.category ?? "-"}</span></td>
                  <td>{recordValue(action.trigger_kind, "kind") ?? "-"}</td>
                  <td><code>{action.execution_path ?? "-"}</code></td>
                  <td><code>{action.rollback_contract}</code></td>
                  <td><span class={`ontology-action-mode is-${action.default_mode}`}>{action.default_mode}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 ? <div class="empty-state">No ActionTypes match these filters.</div> : null}
        </div>

        {selected ? <ActionInspector action={selected} /> : null}
      </div>
    </section>
  );
}

function ActionFilter({
  label,
  value,
  values,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly values: readonly string[];
  readonly onChange: (value: string) => void;
}) {
  return (
    <label class="ontology-action-filter">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange((event.target as HTMLSelectElement).value)}>
        <option value={ALL}>All</option>
        {values.map((item) => <option value={item} key={item}>{item}</option>)}
      </select>
    </label>
  );
}

function ActionInspector({ action }: { readonly action: OntologyActionTypeRecord }) {
  return (
    <aside class="ontology-action-inspector" aria-label="ActionType safety contract">
      <header>
        <span class="eyebrow">ActionType</span>
        <h3><code>{action.name}</code></h3>
        <p>{action.description ?? "No description recorded."}</p>
      </header>

      <section>
        <h4>Identity and routing</h4>
        <dl class="ontology-action-facts">
          <dt>Version</dt><dd>{action.version}</dd>
          <dt>Operation</dt><dd><code>{action.operation}</code></dd>
          <dt>Category</dt><dd>{action.category ?? "-"}</dd>
          <dt>Trigger</dt><dd>{recordValue(action.trigger_kind, "kind") ?? "-"}</dd>
          <dt>Execution</dt><dd><code>{action.execution_path ?? "-"}</code></dd>
          <dt>Environment</dt><dd>{action.env_scope}</dd>
          <dt>Interfaces</dt><dd>{action.interfaces.join(", ") || "-"}</dd>
        </dl>
      </section>

      <section>
        <h4>Safety contract</h4>
        <dl class="ontology-action-facts">
          <dt>Rollback</dt><dd><code>{action.rollback_contract}</code></dd>
          <dt>Irreversible</dt><dd>{action.irreversible ? "Yes" : "No"}</dd>
          <dt>Default mode</dt><dd>{action.default_mode}</dd>
          <dt>Blast radius</dt><dd>{action.blast_radius ? compactRecord(action.blast_radius) : "-"}</dd>
          <dt>Live probe</dt><dd>{action.live_probe_ref ?? "-"}</dd>
        </dl>
      </section>

      <RecordList title="Preconditions" records={action.preconditions} />
      <RecordList title="Stop conditions" records={action.stop_conditions} />
      <RecordFacts title="Promotion gate" record={action.promotion_gate} />
      {action.ceiling_by_tier ? <TierCeilings record={action.ceiling_by_tier} /> : null}
      {action.prod_downgrade ? <RecordFacts title="Production downgrade" record={action.prod_downgrade} /> : null}
    </aside>
  );
}

function RecordList({ title, records }: { readonly title: string; readonly records: readonly UnknownRecord[] }) {
  return (
    <section>
      <h4>{title} <span>{records.length}</span></h4>
      {records.length === 0 ? <p class="muted">None declared.</p> : (
        <ul class="ontology-action-records">
          {records.map((record, index) => <li key={index}>{compactRecord(record)}</li>)}
        </ul>
      )}
    </section>
  );
}

function RecordFacts({ title, record }: { readonly title: string; readonly record: UnknownRecord }) {
  return (
    <section>
      <h4>{title}</h4>
      <dl class="ontology-action-facts">
        {Object.entries(record).map(([key, value]) => (
          <><dt key={`${key}-term`}>{key.replaceAll("_", " ")}</dt><dd key={`${key}-value`}>{formatUnknown(value)}</dd></>
        ))}
      </dl>
    </section>
  );
}

function TierCeilings({ record }: { readonly record: UnknownRecord }) {
  return (
    <section>
      <h4>Tier ceilings</h4>
      <div class="ontology-tier-grid">
        {Object.entries(record).map(([tier, value]) => (
          <div key={tier}>
            <strong>{tier.toUpperCase()}</strong>
            <span>{formatUnknown(value)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function uniqueValues(values: readonly (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}
