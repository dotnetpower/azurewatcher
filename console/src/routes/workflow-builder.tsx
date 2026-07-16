/**
 * Workflow builder route - browse the built-in workflow catalog read-only,
 * or design a new workflow by chatting with a deterministic assistant.
 *
 * Authoring is conversational, not a form: the operator describes what they
 * want in plain words and the designer (workflow-builder.chat.ts / .tsx)
 * asks follow-up questions, proposes options, shows the generated YAML, and
 * lets them dry-test it. Read-only by construction - `POST /workflows/validate`
 * is a pure check and nothing here mutates control-plane state. The output is
 * canonical YAML the operator copies into a `rule-catalog/workflows/<name>.yaml`
 * remediation PR through the git-native path, never a console button
 * (app-shape.instructions.md § Operator console). New workflows are locked to
 * `shadow` mode - promotion to enforce is a separate governance PR
 * (process-automation.md § 6).
 *
 * SRP: this file owns the route shell, the read-only catalog list, and the
 * per-workflow detail drawer. The conversational designer and its engine live
 * in the sibling `workflow-builder.chat*` modules; pure helpers, the intent
 * matcher, and the shared model live in `workflow-builder.{helpers,intent,model}`.
 */

import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, PageHeader, UnavailableState, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import type {
  ActionTypePaletteEntry,
  ActionTypePaletteResponse,
  WorkflowCatalogEntry,
  WorkflowCatalogResponse,
  WorkflowDefinitionCatalogResponse,
  WorkflowDefinitionEntry,
  WorkflowBindingEntry,
} from "../workflow/validate";
import {
  createWorkflowBinding,
  deleteWorkflowBinding,
} from "../workflow/validate";
import type { CombinedData } from "./workflow-builder.model";
import { formatParams } from "./workflow-builder.helpers";
import { WorkflowChat } from "./workflow-builder.chatpanel";
import { PythonTaskWorkbench } from "./workflow-builder.python-task";

// Re-export the pure helpers the vitest suite pins so `./workflow-builder`
// stays a stable public import surface (workflow-builder.test.ts).
export { buildGithubNewFileUrl, humanizeName, suggestStepId } from "./workflow-builder.helpers";
export { suggestDraftFromText } from "./workflow-builder.intent";

export function hasActionTypeRef(step: { readonly action_type_ref?: string | null }): boolean {
  return typeof step.action_type_ref === "string" && step.action_type_ref.trim().length > 0;
}

type WorkflowGroup = "built_in" | "shared" | "mine";

function workflowGroup(value: string | null): WorkflowGroup {
  return value === "shared" || value === "mine" ? value : "built_in";
}

function workflowGroupLabel(value: WorkflowGroup): string {
  if (value === "built_in") return "Built-in";
  if (value === "shared") return "Shared";
  return "Mine";
}

function workflowFromDefinition(definition: WorkflowDefinitionEntry): WorkflowCatalogEntry {
  const document = definition.workflow_document;
  return {
    ...document,
    step_count: document.steps.length,
    yaml: JSON.stringify(document, null, 2),
  };
}

interface Props {
  readonly client: ReadApiClient;
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [palette, catalog, definitions] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
          client.panel<WorkflowDefinitionCatalogResponse>("/workflows/definitions"),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: {
              palette: palette.action_types,
              workflows: catalog.workflows,
              definitions,
            },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message:
                "The workflow authoring routes are not wired on this deployment. " +
                "Set ReadApiConfig.workflow_authoring in the composition root to enable them.",
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
  }, [client]);

  return (
    <div class="stack governance-route workflow-builder-route">
      <PageHeader title={t("route.workflowBuilder")} subtitle={t("workflowBuilder.subtitle")} />
      <AsyncBoundary state={state} resourceLabel="workflow builder">
        {(data) => <WorkflowShell data={data} />}
      </AsyncBoundary>
    </div>
  );
}

/** Top-level view switch: the read-only built-in list, or the conversational
 * designer. Authoring is deliberately gated behind an explicit "design a new
 * workflow" action so the default surface is safe inspection. */
function WorkflowShell({ data }: { readonly data: CombinedData }) {
  const [mode, setMode] = useState<"list" | "new" | "python">("list");

  usePublishViewContext(
    () => {
      const isNew = mode === "new";
      // In the designer, ground the deck in the ActionType palette so "what
      // can this do / what does <action> mean?" is answerable. In the list
      // view, ground it in the shipped workflows instead.
      const records: Record<string, readonly Record<string, unknown>[]> = isNew
        ? {
            action_types: data.palette.map((p) => ({
              name: p.name,
              category: p.category ?? "-",
              rollback: p.rollback_contract,
              hil_tiers: p.hil_tiers.length > 0 ? p.hil_tiers.join(",") : "none",
              summary: p.description ?? "-",
            })),
          }
        : {
            workflows: data.workflows.map((w) => ({
              name: w.name,
              description: w.description ?? "-",
              trigger:
                w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule,
              steps: w.step_count,
              step_actions: w.steps.map((s) => s.action_type_ref).join(" -> "),
              mode: w.default_mode,
            })),
          };
      return {
        routeId: "workflow-builder",
        routeLabel: "Workflow builder",
        purpose:
          "Inspect the built-in workflows (a trigger plus an ordered chain of " +
          "ActionType steps) and design a new one by chatting with the builder. " +
          "New workflows are locked to shadow mode; promotion to enforce is a " +
          "separate reviewed PR. Read-only by construction.",
        glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.mode]),
        headline: isNew
          ? `Conversational workflow designer open - ${data.palette.length} ActionTypes available`
          : `${data.workflows.length} built-in workflows - ${data.palette.length} ActionTypes`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "built_in_count", value: data.workflows.length, group: "workflow" },
          { key: "palette_size", value: data.palette.length, group: "workflow" },
          { key: "mode", value: isNew ? "new (chat designer)" : "list", group: "workflow" },
          ...(isNew
            ? [
                {
                  key: "default_mode",
                  value: "shadow (locked; promotion is a separate PR)",
                  group: "workflow",
                },
              ]
            : []),
        ],
        records,
      };
    },
    [data.workflows, data.palette, mode],
  );

  if (mode === "new") {
    return <WorkflowChat palette={data.palette} onBack={() => setMode("list")} />;
  }
  if (mode === "python") {
    return <PythonTaskWorkbench onBack={() => setMode("list")} />;
  }
  return (
    <BuiltInList
      workflows={data.workflows}
      definitions={data.definitions}
      palette={data.palette}
      onNew={() => setMode("new")}
      onPython={() => setMode("python")}
    />
  );
}

/** Read-only list of shipped workflows + a details drawer per row, fronted by
 * a single call-to-action that opens the conversational designer. */
function BuiltInList({
  workflows,
  definitions,
  palette,
  onNew,
  onPython,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onNew: () => void;
  readonly onPython: () => void;
}) {
  const initialGroup = workflowGroup(currentRoute().search.get("group"));
  const [group, setGroup] = useState<WorkflowGroup>(initialGroup);
  const groupedWorkflows = group === "built_in"
    ? workflows
    : definitions.groups[group].map(workflowFromDefinition);
  const defaultWorkflow = groupedWorkflows.find((workflow) =>
    workflow.steps.some(hasActionTypeRef),
  ) ?? groupedWorkflows[0] ?? null;
  const requestedWorkflow = currentRoute().search.get("workflow");
  const requestedAction = currentRoute().search.get("action");
  const initialWorkflow = groupedWorkflows.find((workflow) => workflow.name === requestedWorkflow) ??
    groupedWorkflows.find((workflow) => workflow.steps.some((step) => step.action_type_ref === requestedAction)) ??
    defaultWorkflow;
  const [selected, setSelected] = useState<string | null>(initialWorkflow?.name ?? null);
  const [filter, setFilter] = useState("");
  const [bindings, setBindings] = useState<readonly WorkflowBindingEntry[]>(definitions.bindings);
  const current = groupedWorkflows.find((w) => w.name === selected) ?? null;
  const currentDefinition = current
    ? definitions.groups[group].find((definition) => definition.workflow_name === current.name) ?? null
    : null;
  useEffect(() => {
    if (current !== null || defaultWorkflow === null) return;
    setSelected(defaultWorkflow.name);
  }, [current, defaultWorkflow]);
  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const workflowName = route.search.get("workflow");
      const actionName = route.search.get("action");
      const nextGroup = workflowGroup(route.search.get("group"));
      setGroup(nextGroup);
      const available = nextGroup === "built_in"
        ? workflows
        : definitions.groups[nextGroup].map(workflowFromDefinition);
      const requested = available.find((workflow) => workflow.name === workflowName) ??
        available.find((workflow) => workflow.steps.some((step) => step.action_type_ref === actionName)) ??
        defaultWorkflow;
      setSelected(requested?.name ?? null);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [defaultWorkflow, definitions.groups, workflows]);
  const openWorkflow = (workflow: WorkflowCatalogEntry | null): void => {
    navigate(routeHref("workflow-builder", {
      params: { group, workflow: workflow?.name, step: null, action: null },
    }));
  };

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? groupedWorkflows.filter((w) => {
        const trig =
          w.trigger.kind === "signal" ? w.trigger.signal_type ?? "" : w.trigger.schedule ?? "";
        return (
          w.name.toLowerCase().includes(needle) ||
          w.trigger.kind.includes(needle) ||
          trig.toLowerCase().includes(needle) ||
          w.default_mode.includes(needle)
        );
      })
    : groupedWorkflows;
  const shadowCount = groupedWorkflows.filter((w) => w.default_mode !== "enforce").length;
  const enforceCount = groupedWorkflows.length - shadowCount;

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Catalog workflows are read-only here.</strong> A workflow is a business process - a
        trigger plus an ordered chain of actions the control plane runs for you, each with a
        built-in safety net (stop-condition, rollback, blast-radius cap, audit). Describe what you
        want in plain words; the designer asks a few questions, shows you the exact YAML and a
        visual of how it runs, and lets you test it. YAML changes land through a PR. The Python
        task workbench uses its own validated artifact and typed proposal path.
      </div>

      <div class="section-header workflow-builder-actions">
        <button type="button" class="btn" onClick={onNew}>
          + Design a new workflow
        </button>
        <button type="button" class="btn" onClick={onPython}>
          Author Python VM task
        </button>
      </div>

      <section class="stack-section">
        <nav class="workflow-origin-tabs" aria-label="Workflow ownership">
          {(["built_in", "shared", "mine"] as const).map((value) => (
            <a
              key={value}
              href={routeHref("workflow-builder", { params: { group: value } })}
              class={group === value ? "is-active" : undefined}
              aria-current={group === value ? "page" : undefined}
            >
              <span>{workflowGroupLabel(value)}</span>
              <strong>{value === "built_in" ? workflows.length : definitions.groups[value].length}</strong>
            </a>
          ))}
        </nav>
        <div class="section-header">
          <h3 class="section-title">
            {workflowGroupLabel(group)} workflows ({groupedWorkflows.length})
          </h3>
        </div>
        <p class="muted small">
          The shipped workflows, for reference: open a row to see every step and the raw YAML.
        </p>
        {groupedWorkflows.length === 0 ? (
          <p class="muted small">No workflows are available in this group.</p>
        ) : (
          <>
            <div class="list-toolbar">
              <input
                class="form-input"
                type="search"
                value={filter}
                placeholder="Filter by name, trigger, or mode..."
                aria-label="Filter workflows"
                onInput={(e) => setFilter((e.target as HTMLInputElement).value)}
              />
              <span class="muted small">
                Showing {shown.length} of {groupedWorkflows.length} - {shadowCount} shadow,{" "}
                {enforceCount} enforce
              </span>
            </div>
            <div class="scroll">
              <table class="data-table data-table-clickable">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trigger</th>
                    <th>Steps</th>
                    <th>Mode</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((w) => {
                    const isOpen = w.name === selected;
                    const toggle = () => openWorkflow(isOpen ? null : w);
                    return (
                      <tr
                        key={w.name}
                        class={isOpen ? "row-active" : ""}
                        onClick={toggle}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggle();
                          }
                        }}
                        tabIndex={0}
                        role="button"
                        aria-expanded={isOpen}
                        style="cursor: pointer"
                      >
                        <td class="mono">{w.name}</td>
                        <td class="mono muted">
                          <span class="badge tag">{w.trigger.kind}</span>{" "}
                          {w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule}
                        </td>
                        <td>{w.step_count}</td>
                        <td>
                          <span
                            class={w.default_mode === "enforce" ? "badge enforce" : "badge shadow"}
                          >
                            {w.default_mode}
                          </span>
                        </td>
                        <td class="chevron-col">
                          <span class="row-chevron">{isOpen ? "▾" : "▸"}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <WorkflowAutomations
        bindings={bindings}
        definitions={definitions}
        selectedDefinition={currentDefinition}
        onCreated={(binding) => setBindings((items) => [...items, binding])}
        onDeleted={(bindingId) => setBindings((items) =>
          items.filter((binding) => binding.binding_id !== bindingId),
        )}
      />

      {current ? <WorkflowDetail workflow={current} palette={palette} /> : null}
    </div>
  );
}

function WorkflowAutomations({
  bindings,
  definitions,
  selectedDefinition,
  onCreated,
  onDeleted,
}: {
  readonly bindings: readonly WorkflowBindingEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly selectedDefinition: WorkflowDefinitionEntry | null;
  readonly onCreated: (binding: WorkflowBindingEntry) => void;
  readonly onDeleted: (bindingId: string) => void;
}) {
  const [trigger, setTrigger] = useState<"deck_open" | "schedule" | "signal">("deck_open");
  const [cronExpression, setCronExpression] = useState("0 7 * * *");
  const [timezone, setTimezone] = useState("Asia/Seoul");
  const [signalType, setSignalType] = useState("object.event");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const definitionById = new Map(
    Object.values(definitions.groups)
      .flat()
      .map((definition) => [definition.definition_id, definition] as const),
  );

  const createBinding = async (): Promise<void> => {
    if (selectedDefinition === null) return;
    setSaving(true);
    try {
      const binding = await createWorkflowBinding({
        definition_id: selectedDefinition.definition_id,
        trigger,
        ...(trigger === "schedule" ? { cron_expression: cronExpression, timezone } : {}),
        ...(trigger === "signal" ? { signal_type: signalType } : {}),
      });
      onCreated(binding);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  const removeBinding = async (binding: WorkflowBindingEntry): Promise<void> => {
    const definition = definitionById.get(binding.definition_id);
    const workflowName = definition?.workflow_name ?? binding.definition_id;
    if (!window.confirm(`Remove the ${workflowName} configuration?`)) return;
    setSaving(true);
    try {
      await deleteWorkflowBinding(binding.binding_id);
      onDeleted(binding.binding_id);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section class="workflow-automation-section">
      <header>
        <div>
          <h3>My automations <span>{bindings.length}</span></h3>
          <p>
            Save a principal-scoped trigger configuration. Runtime dispatch is not active yet;
            ActionType ceilings remain authoritative when activation lands.
          </p>
        </div>
      </header>
      {error ? <p class="error-text">{error}</p> : null}
      <div class="workflow-automation-layout">
        <div class="workflow-binding-list">
          {bindings.map((binding) => {
            const definition = definitionById.get(binding.definition_id);
            return (
              <article key={binding.binding_id}>
                <div>
                  <strong>{definition?.workflow_name ?? binding.definition_id}</strong>
                  <span>{binding.trigger.replaceAll("_", " ")}</span>
                  <small>
                    {binding.trigger === "schedule"
                      ? `${binding.cron_expression} - ${binding.timezone}`
                      : binding.signal_type ?? "configured, not active"}
                  </small>
                </div>
                <button
                  type="button"
                  class="secondary"
                  disabled={saving}
                  onClick={() => void removeBinding(binding)}
                >
                  Remove
                </button>
              </article>
            );
          })}
          {bindings.length === 0 ? <p class="muted small">No personal automations.</p> : null}
        </div>

        <div class="workflow-binding-create">
          <strong>
            {selectedDefinition
              ? `Use ${selectedDefinition.workflow_name}`
              : "Select a workflow definition"}
          </strong>
          <label>
            <span>Trigger</span>
            <select
              value={trigger}
              disabled={selectedDefinition === null}
              onChange={(event) => setTrigger(event.currentTarget.value as typeof trigger)}
            >
              <option value="deck_open">Command Deck opens</option>
              <option value="schedule">Schedule</option>
              <option value="signal">Signal</option>
            </select>
          </label>
          {trigger === "schedule" ? (
            <>
              <label>
                <span>Cron expression</span>
                <input value={cronExpression} onInput={(event) => setCronExpression(event.currentTarget.value)} />
              </label>
              <label>
                <span>Timezone</span>
                <input value={timezone} onInput={(event) => setTimezone(event.currentTarget.value)} />
              </label>
            </>
          ) : null}
          {trigger === "signal" ? (
            <label>
              <span>Signal type</span>
              <input value={signalType} onInput={(event) => setSignalType(event.currentTarget.value)} />
            </label>
          ) : null}
          <button
            type="button"
            class="btn"
            disabled={saving || selectedDefinition === null}
            onClick={() => void createBinding()}
          >
            Save configuration
          </button>
        </div>
      </div>
    </section>
  );
}

/** Read-only detail: property table + steps + raw catalog YAML. */
function WorkflowDetail({
  workflow,
  palette,
}: {
  readonly workflow: WorkflowCatalogEntry;
  readonly palette: readonly ActionTypePaletteEntry[];
}) {
  const gate = workflow.promotion_gate;
  const requestedStep = currentRoute().search.get("step");
  const requestedAction = currentRoute().search.get("action");
  const matchedRequestedStep = requestedStep
    ? workflow.steps.find((step) => step.id === requestedStep) ?? null
    : null;
  const invalidRequestedStep = requestedStep !== null && matchedRequestedStep === null;
  const defaultStep = requestedStep !== null
    ? matchedRequestedStep
    : workflow.steps.find((step) => step.action_type_ref === requestedAction) ??
      workflow.steps.find(hasActionTypeRef) ?? workflow.steps[0] ?? null;
  const [selectedStep, setSelectedStep] = useState<string | null>(defaultStep?.id ?? null);
  const selected = workflow.steps.find((step) => step.id === selectedStep) ?? defaultStep;
  useEffect(() => {
    if (selectedStep === selected?.id) return;
    setSelectedStep(selected?.id ?? null);
  }, [selected?.id, selectedStep]);
  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const stepId = route.search.get("step");
      const actionName = route.search.get("action");
      const requested = stepId !== null
        ? workflow.steps.find((step) => step.id === stepId) ?? null
        : workflow.steps.find((step) => step.action_type_ref === actionName) ?? defaultStep;
      setSelectedStep(requested?.id ?? null);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [defaultStep, workflow.steps]);
  const openStep = (stepId: string): void => {
    navigate(routeHref("workflow-builder", {
      params: { workflow: workflow.name, step: stepId },
    }));
  };
  const actionType = selected
    ? palette.find((entry) => entry.name === selected.action_type_ref) ?? null
    : null;
  return (
    <section class="workflow-catalog-workspace">
      <aside class="workflow-palette-panel">
        <h3>Palette <span>{palette.length} ActionTypes</span></h3>
        <p>Available on this deployment. Catalog view is read-only.</p>
        <ul>
          {palette.map((entry) => (
            <li key={entry.name}>
              <code>{entry.name}</code>
              <span class={`is-${entry.category ?? "other"}`}>{entry.category ?? "other"}</span>
            </li>
          ))}
        </ul>
      </aside>

      <section class="workflow-canvas-panel">
        <header>
          <div>
            <h3>{workflow.name}</h3>
            <p>{workflow.description ?? "Published workflow catalog entry"}</p>
          </div>
          <span class={workflow.default_mode === "enforce" ? "status-pill status-pill-enforce" : "status-pill status-pill-shadow"}>
            {workflow.default_mode}
          </span>
        </header>
        <div class="workflow-canvas-chain">
          <div class="workflow-canvas-node is-trigger">
            <span>when</span>
            <strong>{workflow.trigger.kind}</strong>
            <code>{workflow.trigger.kind === "signal" ? workflow.trigger.signal_type : workflow.trigger.schedule}</code>
          </div>
          {workflow.steps.map((step, index) => (
            <div class="workflow-canvas-step" key={step.id}>
              <i aria-hidden="true" />
              <button
                type="button"
                class={`workflow-canvas-node is-action ${selected?.id === step.id ? "is-selected" : ""}`}
                onClick={() => openStep(step.id)}
              >
                <span>{index === workflow.steps.length - 1 ? "then" : "do"}</span>
                <strong>{step.id}</strong>
                <code>{step.action_type_ref || step.guard_rule_ref || step.on_failure || "workflow stage"}</code>
              </button>
            </div>
          ))}
          <div class="workflow-canvas-step">
            <i aria-hidden="true" />
            <div class="workflow-canvas-node is-done"><span>done</span><strong>audit terminal state</strong></div>
          </div>
        </div>
      </section>

      <aside class="workflow-inspector-panel">
        <h3>Inspect <span>selected step</span></h3>
        {invalidRequestedStep ? (
          <UnavailableState message={`Step ${requestedStep} is not registered in ${workflow.name}.`} />
        ) : selected ? (
          <>
            <code class="workflow-inspector-name">{selected.action_type_ref || selected.id}</code>
            <dl>
              <div><dt>Step id</dt><dd>{selected.id}</dd></div>
              <div><dt>Category</dt><dd>{actionType?.category ?? "not recorded"}</dd></div>
              <div><dt>Execution path</dt><dd>{actionType?.execution_path ?? "not recorded"}</dd></div>
              <div><dt>Rollback</dt><dd>{actionType?.rollback_contract ?? "not recorded"}</dd></div>
              <div><dt>Default mode</dt><dd>{actionType?.default_mode ?? workflow.default_mode}</dd></div>
              <div><dt>Guard</dt><dd>{selected.guard_rule_ref ?? "none"}</dd></div>
              <div><dt>Compensated by</dt><dd>{selected.compensated_by ?? "none"}</dd></div>
              <div><dt>On failure</dt><dd>{selected.on_failure ?? "not recorded"}</dd></div>
              <div><dt>Parameters</dt><dd>{formatParams(selected.params)}</dd></div>
            </dl>
          </>
        ) : <p class="muted">This workflow has no steps.</p>}
        <div class="workflow-promotion-facts">
          <strong>Promotion gate</strong>
          <span>{gate.min_shadow_days}d shadow</span>
          <span>{gate.min_samples} samples</span>
          <span>accuracy &ge; {gate.min_accuracy}</span>
          <span>escapes &le; {gate.max_policy_escapes}</span>
        </div>
      </aside>

      <details class="workflow-yaml-panel">
        <summary>Published YAML and anti-scope</summary>
        {workflow.anti_scope ? <p><strong>Anti-scope:</strong> {workflow.anti_scope}</p> : null}
        <div class="code-actions"><CopyButton text={workflow.yaml} label="Copy YAML" /></div>
        <pre class="mono scroll code-block">{workflow.yaml}</pre>
      </details>
    </section>
  );
}
