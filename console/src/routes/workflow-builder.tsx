/**
 * Workflow builder panel - author a custom business process by mapping
 * ordered steps onto the ontology ActionType catalog.
 *
 * Read-only by construction. The palette is `GET /workflows/action-types`
 * and validation is `POST /workflows/validate` (a pure server-side check;
 * see `workflow/validate.ts`). Nothing here mutates control-plane state:
 * the output is a canonical YAML the operator copies into a
 * `rule-catalog/workflows/<name>.yaml` file and lands as a remediation PR
 * through the git-native path, never a console button
 * (app-shape.instructions.md § Operator console). New workflows are locked
 * to `shadow` mode - promotion to enforce is a separate governance PR
 * (process-automation.md § 6).
 *
 * SRP: this file owns the React component tree only. Pure helpers, static
 * option catalogs, and the plain-language intent matcher live in sibling
 * modules:
 *   - workflow-builder.model.ts   (types + static option catalogs)
 *   - workflow-builder.helpers.ts (pure fns; also imported by tests)
 *   - workflow-builder.intent.ts  (plain-text -> draft matcher)
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Fragment } from "preact";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  type ActionTypePaletteEntry,
  type ActionTypePaletteResponse,
  type ValidateResponse,
  type WorkflowCatalogEntry,
  type WorkflowCatalogResponse,
  validateWorkflowDraft,
} from "../workflow/validate";
import {
  BUILDER_FORM_FIELDS,
  CUSTOM_SIGNAL,
  INITIAL_FORM,
  INTENT_EXAMPLES,
  KNOWN_SIGNAL_VALUES,
  NAME_PATTERN,
  SCHEDULE_PRESETS,
  SIGNAL_TYPE_OPTIONS,
  type CombinedData,
  type DraftStep,
  type FormState,
} from "./workflow-builder.model";
import {
  buildDraft,
  catalogToForm,
  emptyStep,
  formatParams,
  githubNewFileUrl,
  humanizeActionName,
  humanizeIssueKey,
  humanizeName,
  signalLabel,
  suggestStepId,
} from "./workflow-builder.helpers";
import { suggestDraftFromText } from "./workflow-builder.intent";

// Re-export the pure helpers the vitest suite pins so `./workflow-builder`
// stays a stable public import surface (workflow-builder.test.ts).
export { buildGithubNewFileUrl, humanizeName, suggestStepId } from "./workflow-builder.helpers";
export { suggestDraftFromText } from "./workflow-builder.intent";

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
        const [palette, catalog] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: { palette: palette.action_types, workflows: catalog.workflows },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes("404")) {
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
    <div class="stack">
      <PageHeader title={t("route.workflowBuilder")} subtitle={t("workflowBuilder.subtitle")} />
      <AsyncBoundary state={state} resourceLabel="workflow builder">
        {(data) => <WorkflowShell data={data} />}
      </AsyncBoundary>
    </div>
  );
}

/** Top-level view switch: the read-only built-in list, or the new-workflow
 * builder. Authoring is deliberately gated behind an explicit "New
 * workflow" action so the default surface is safe inspection. */
function WorkflowShell({ data }: { readonly data: CombinedData }) {
  const [mode, setMode] = useState<"list" | "new">("list");
  const [seed, setSeed] = useState<FormState | null>(null);

  usePublishViewContext(
    () => {
      const isNew = mode === "new";
      // In the builder ("new") the operator is filling a form; ground the deck
      // in the form schema, the selectable trigger signals, and the ActionType
      // palette so "what do I enter / select here?" is answerable. In the list
      // view, ground it in the shipped workflows instead.
      const records: Record<string, readonly Record<string, unknown>[]> = isNew
        ? {
            form_fields: BUILDER_FORM_FIELDS,
            trigger_signal_options: [
              ...SIGNAL_TYPE_OPTIONS.map((o) => ({ value: o.value, hint: o.hint })),
              { value: "(custom)", hint: "choose Custom to type any other signal_type string" },
            ],
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
          "ActionType steps) and author a new one. New workflows are locked to " +
          "shadow mode; promotion to enforce is a separate reviewed PR. " +
          "Read-only inspection by default.",
        glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.mode]),
        headline: isNew
          ? `New-workflow builder open - fill the form; ${data.palette.length} ActionTypes to choose from`
          : `${data.workflows.length} built-in workflows - ${data.palette.length} ActionTypes`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "built_in_count", value: data.workflows.length, group: "workflow" },
          { key: "palette_size", value: data.palette.length, group: "workflow" },
          { key: "mode", value: isNew ? "new (builder form open)" : "list", group: "workflow" },
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
    return (
      <BuilderBody
        palette={data.palette}
        initial={seed ?? INITIAL_FORM}
        onBack={() => setMode("list")}
      />
    );
  }
  return (
    <BuiltInList
      workflows={data.workflows}
      palette={data.palette}
      onNew={() => {
        setSeed(null);
        setMode("new");
      }}
      onClone={(w) => {
        setSeed(catalogToForm(w));
        setMode("new");
      }}
      onDraft={(form) => {
        setSeed(form);
        setMode("new");
      }}
    />
  );
}

/** Live "when -> do" summary of the draft, mirroring Palantir Automate's
 * condition -> effect mental model. Updates as the operator edits the
 * trigger and steps so the workflow reads as one plain sentence before any
 * validation. */
function WorkflowSummary({ form }: { readonly form: FormState }) {
  const triggerVerb = form.triggerKind === "signal" ? "When" : "On schedule";
  const triggerLabel =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType.trim() || "an event"
      : form.schedule.trim() || "a schedule";
  const actions = form.steps.map((s) => s.action_type_ref.trim()).filter(Boolean);
  return (
    <div class="wf-summary" aria-live="polite">
      <span class="wf-summary-clause">
        <span class="wf-summary-label">{triggerVerb}</span> <code>{triggerLabel}</code>
      </span>
      <span class="wf-summary-arrow" aria-hidden="true">
        →
      </span>
      <span class="wf-summary-clause">
        <span class="wf-summary-label">do</span>{" "}
        {actions.length === 0 ? (
          <span class="muted">(add a step)</span>
        ) : (
          actions.map((a, i) => (
            <Fragment key={i}>
              {i > 0 ? <span class="wf-summary-then"> then </span> : null}
              <code title={a}>{humanizeActionName(a)}</code>
            </Fragment>
          ))
        )}
      </span>
    </div>
  );
}

/** A horizontal, clickable flow map of the draft (trigger -> steps -> end),
 * the graphical companion to the "when -> do" summary. Each step node jumps
 * to its editor card and surfaces the branch/rollback structure (guard,
 * compensated-by, on-failure) that a flat card list hides. */
function WorkflowFlow({
  form,
  onSelect,
}: {
  readonly form: FormState;
  readonly onSelect: (key: number) => void;
}) {
  const triggerLabel =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType.trim() || "event"
      : form.schedule.trim() || "schedule";
  return (
    <div class="wf-flow" role="list" aria-label="Workflow flow map">
      <div class="wf-node wf-node-trigger" role="listitem">
        <span class="wf-node-kind">{form.triggerKind === "signal" ? "when" : "on"}</span>
        <span class="wf-node-title mono">{triggerLabel}</span>
      </div>
      {form.steps.map((step, index) => {
        const action = step.action_type_ref.trim();
        return (
          <Fragment key={step.key}>
            <span class="wf-flow-arrow" aria-hidden="true">
              →
            </span>
            <button
              type="button"
              class={action ? "wf-node" : "wf-node wf-node-empty"}
              role="listitem"
              onClick={() => onSelect(step.key)}
              title={action ? `Jump to step: ${action}` : "Jump to this step"}
            >
              <span class="wf-node-kind">#{index + 1}</span>
              <span class="wf-node-title">{action ? humanizeActionName(action) : "unset"}</span>
              <span class="wf-node-badges" aria-hidden="true">
                {step.guard_rule_ref.trim() ? <span title="Guarded">🛡</span> : null}
                {step.compensated_by.trim() ? <span title="Has rollback">↩</span> : null}
                {step.on_failure.trim() ? <span title="Has on-failure fallback">⤵</span> : null}
              </span>
            </button>
          </Fragment>
        );
      })}
      <span class="wf-flow-arrow" aria-hidden="true">
        →
      </span>
      <div class="wf-node wf-node-end" role="listitem">
        <span class="wf-node-title">done</span>
      </div>
    </div>
  );
}

/** Plain-language composer: describe the automation in words and get a
 * matching trigger + steps to start from. Deterministic and read-only -
 * it pre-fills the builder, never creates anything. Abstains (shows a
 * gentle nudge) when it cannot match confidently. */
function IntentComposer({
  palette,
  onUse,
}: {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onUse: (form: FormState) => void;
}) {
  const [text, setText] = useState("");
  const suggestion = useMemo(() => suggestDraftFromText(text, palette), [text, palette]);
  const typed = text.trim().length >= 3;
  return (
    <section class="stack-section intent-composer">
      <h3 class="section-title">Describe what you want</h3>
      <p class="muted small">
        Type it in plain words and the builder suggests a matching trigger and steps you can
        adjust. Nothing is created until you validate and open a PR.
      </p>
      <textarea
        class="form-input intent-input"
        rows={2}
        value={text}
        aria-label="Describe the workflow in plain words"
        placeholder="e.g. When cost spikes, right-size the VM and tell me"
        onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
      />
      <div class="intent-examples">
        <span class="muted small">Try:</span>
        {INTENT_EXAMPLES.map((ex) => (
          <button type="button" class="chip-btn" key={ex} onClick={() => setText(ex)}>
            {ex}
          </button>
        ))}
      </div>
      {typed ? (
        suggestion ? (
          <div class="intent-preview" aria-live="polite">
            <WorkflowSummary form={suggestion.form} />
            <ul class="intent-reasons">
              {suggestion.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            <button type="button" class="btn" onClick={() => onUse(suggestion.form)}>
              Use this draft →
            </button>
          </div>
        ) : (
          <p class="field-hint" aria-live="polite">
            No confident match yet. Add a bit more detail (an action like "right-size" or "encrypt",
            or a trigger like "cost" or "weekly"), or pick a template below.
          </p>
        )
      ) : null}
    </section>
  );
}

/** Launchpad: a card grid that lets an operator start a new workflow from a
 * shipped template (clone-and-tweak) or from a blank form. Replacing the
 * blank-form-first flow removes the "empty canvas" problem - the default
 * surface is now "pick something close and adjust". */
function TemplateGallery({
  workflows,
  onNew,
  onClone,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly onNew: () => void;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
}) {
  return (
    <section class="stack-section">
      <h3 class="section-title">Or start from an example</h3>
      <p class="muted small">
        Pick a shipped workflow that is close to what you want and adjust it, or start from a
        blank form. Either way the draft opens in the builder - nothing is created until you
        validate and open a PR.
      </p>
      <div class="template-gallery">
        {workflows.map((w) => (
          <button
            type="button"
            class="template-card"
            key={w.name}
            onClick={() => onClone(w)}
          >
            <span class="template-card-title">{humanizeName(w.name)}</span>
            <span class="template-card-desc">{w.description ?? "No description."}</span>
            <span class="template-card-meta">
              <span class="badge tag">
                {w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule}
              </span>
              <span class="muted small">
                {w.step_count} step{w.step_count === 1 ? "" : "s"}
              </span>
            </span>
            <span class="template-card-cta">Use as template →</span>
          </button>
        ))}
        <button
          type="button"
          class="template-card template-card-blank"
          onClick={onNew}
        >
          <span class="template-card-title">Start from scratch</span>
          <span class="template-card-desc">
            Begin with an empty form and map each step onto an ActionType yourself.
          </span>
          <span class="template-card-cta">Blank workflow →</span>
        </button>
      </div>
    </section>
  );
}

/** Read-only list of shipped workflows + a details drawer per row. */
function BuiltInList({
  workflows,
  palette,
  onNew,
  onClone,
  onDraft,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onNew: () => void;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
  readonly onDraft: (form: FormState) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const current = workflows.find((w) => w.name === selected) ?? null;

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? workflows.filter((w) => {
        const trig = w.trigger.kind === "signal" ? w.trigger.signal_type ?? "" : w.trigger.schedule ?? "";
        return (
          w.name.toLowerCase().includes(needle) ||
          w.trigger.kind.includes(needle) ||
          trig.toLowerCase().includes(needle) ||
          w.default_mode.includes(needle)
        );
      })
    : workflows;
  const shadowCount = workflows.filter((w) => w.default_mode !== "enforce").length;
  const enforceCount = workflows.length - shadowCount;

  return (
    <div class="stack">
      <div class="callout">
        <strong>What is this?</strong> A workflow is a business process - a trigger plus an
        ordered chain of actions the control plane runs for you, each with a built-in safety net
        (stop-condition, rollback, blast-radius cap, audit). Three ways to begin: <strong>describe
        it</strong> in plain words, start from an <strong>example</strong>, or <strong>browse</strong>
        the full catalog for reference. Nothing is created until you validate and open a PR.
      </div>

      <IntentComposer palette={palette} onUse={onDraft} />

      <TemplateGallery workflows={workflows} onNew={onNew} onClone={onClone} />

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Browse the full catalog ({workflows.length})</h3>
        </div>
        <p class="muted small">
          The same shipped workflows, for reference: open a row to see every step and the raw
          YAML. Any row can also be opened as a starting point ("Use as template").
        </p>
        {workflows.length === 0 ? (
          <p class="muted small">No built-in workflows are served on this deployment.</p>
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
                Showing {shown.length} of {workflows.length} - {shadowCount} shadow,{" "}
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
                    const toggle = () => setSelected(isOpen ? null : w.name);
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

      {current ? <WorkflowDetail workflow={current} onClone={onClone} /> : null}
    </div>
  );
}

/** Read-only detail: property table + steps + raw catalog YAML. */
function WorkflowDetail({
  workflow,
  onClone,
}: {
  readonly workflow: WorkflowCatalogEntry;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
}) {
  const gate = workflow.promotion_gate;
  return (
    <section class="stack-section">
      <div class="section-header">
        <h3 class="section-title mono">{workflow.name}</h3>
        <button type="button" class="btn btn-small" onClick={() => onClone(workflow)}>
          Use as template
        </button>
      </div>
      {workflow.description ? <p class="muted">{workflow.description}</p> : null}
      <div class="prop-grid">
        <div class="prop">
          <span class="prop-label">Version</span>
          <span class="mono">{workflow.version}</span>
        </div>
        <div class="prop">
          <span class="prop-label">Trigger</span>
          <span class="mono">
            {workflow.trigger.kind}:{" "}
            {workflow.trigger.kind === "signal"
              ? workflow.trigger.signal_type
              : workflow.trigger.schedule}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Default mode</span>
          <span class={workflow.default_mode === "enforce" ? "badge enforce" : "badge shadow"}>
            {workflow.default_mode}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Promotion gate</span>
          <span class="mono small">
            {gate.min_shadow_days}d, {gate.min_samples} samples, acc &ge; {gate.min_accuracy},
            escapes &le; {gate.max_policy_escapes}
          </span>
        </div>
      </div>

      <h4 class="section-subtitle">Steps ({workflow.steps.length})</h4>
      <div class="scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Step id</th>
              <th>ActionType</th>
              <th>Guard</th>
              <th>Compensated by</th>
              <th>On failure</th>
              <th>Params</th>
            </tr>
          </thead>
          <tbody>
            {workflow.steps.map((s, i) => (
              <tr key={s.id}>
                <td>{i + 1}</td>
                <td class="mono">{s.id}</td>
                <td class="mono">{s.action_type_ref}</td>
                <td class="mono muted">{s.guard_rule_ref ?? "-"}</td>
                <td class="mono muted">{s.compensated_by ?? "-"}</td>
                <td class="mono muted">{s.on_failure ?? "-"}</td>
                <td class="mono muted">{formatParams(s.params)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {workflow.anti_scope ? (
        <p class="muted small">
          <strong>Anti-scope:</strong> {workflow.anti_scope}
        </p>
      ) : null}

      <div class="code-actions">
        <CopyButton text={workflow.yaml} label="Copy YAML" />
      </div>
      <pre class="mono scroll code-block">{workflow.yaml}</pre>
    </section>
  );
}

function BuilderBody({
  palette,
  initial,
  onBack,
}: {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly initial: FormState;
  readonly onBack: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const [nextKey, setNextKey] = useState(initial.steps.length);
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [validating, setValidating] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  // Monotonic token: bumped on every validate AND every edit, so a slow
  // validate response that arrives after the draft changed is discarded.
  const validateTokenRef = useRef(0);

  // Move focus to the first field when the builder opens (keyboard + SR
  // users land on the form, not the top of the page).
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Bring the validation outcome into view - on a long form the result
  // section sits below the fold and is easy to miss.
  useEffect(() => {
    if (result || transportError) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [result, transportError]);

  const paletteByName = useMemo(
    () => new Map(palette.map((p) => [p.name, p])),
    [palette],
  );

  // ActionType options grouped by category so the step dropdowns are
  // scannable (30+ actions in one flat list is a guessing game).
  const groupedPalette = useMemo(() => {
    const byCat = new Map<string, ActionTypePaletteEntry[]>();
    for (const p of palette) {
      const cat = p.category ?? "other";
      const arr = byCat.get(cat);
      if (arr) arr.push(p);
      else byCat.set(cat, [p]);
    }
    return [...byCat.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [palette]);

  function requestBack(): void {
    if (dirty && !window.confirm("Discard this draft and return to the list?")) return;
    onBack();
  }

  function invalidateAfterEdit(): void {
    setResult(null);
    setDirty(true);
    // Any edit supersedes an in-flight validate response (stale-result guard).
    validateTokenRef.current += 1;
  }

  function patch(fields: Partial<FormState>): void {
    setForm((prev) => ({ ...prev, ...fields }));
    invalidateAfterEdit();
  }

  function patchStep(key: number, fields: Partial<DraftStep>): void {
    setForm((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => (s.key === key ? { ...s, ...fields } : s)),
    }));
    invalidateAfterEdit();
  }

  function addStep(): void {
    setForm((prev) => ({ ...prev, steps: [...prev.steps, emptyStep(nextKey)] }));
    setNextKey((k) => k + 1);
    invalidateAfterEdit();
  }

  function removeStep(key: number): void {
    setForm((prev) => ({ ...prev, steps: prev.steps.filter((s) => s.key !== key) }));
    invalidateAfterEdit();
  }

  function moveStep(index: number, delta: number): void {
    setForm((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.steps.length) return prev;
      const next = [...prev.steps];
      const a = next[index];
      const b = next[target];
      if (a === undefined || b === undefined) return prev;
      next[index] = b;
      next[target] = a;
      return { ...prev, steps: next };
    });
    invalidateAfterEdit();
  }

  function selectStep(key: number): void {
    const el = document.getElementById(`wf-step-${key}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("step-card-flash");
    window.setTimeout(() => el?.classList.remove("step-card-flash"), 900);
  }

  async function onValidate(): Promise<void> {
    // Guard against a stale response overwriting a newer edit: each run gets a
    // token; a resolved request only applies if it is still the latest.
    const token = validateTokenRef.current + 1;
    validateTokenRef.current = token;
    setValidating(true);
    setTransportError(null);
    setResult(null);
    try {
      const res = await validateWorkflowDraft(buildDraft(form));
      if (validateTokenRef.current !== token) return;
      setResult(res);
    } catch (err) {
      if (validateTokenRef.current !== token) return;
      setTransportError(err instanceof Error ? err.message : String(err));
    } finally {
      if (validateTokenRef.current === token) setValidating(false);
    }
  }

  function resetForm(): void {
    setForm(INITIAL_FORM);
    setNextKey(1);
    setResult(null);
    setTransportError(null);
    setDirty(false);
  }

  const stepIds = form.steps.map((s) => s.id.trim()).filter(Boolean);

  // Client-side readiness: what still blocks a useful validate call. Shown
  // as a checklist so the operator is never guessing why Validate is off.
  const nameValid = NAME_PATTERN.test(form.name.trim());
  const triggerFilled =
    form.triggerKind === "signal" ? form.signalType.trim() !== "" : form.schedule.trim() !== "";
  const incompleteSteps = form.steps.filter(
    (s) => s.id.trim() === "" || s.action_type_ref.trim() === "",
  ).length;
  const missing: string[] = [];
  if (!nameValid) missing.push(form.name.trim() === "" ? "a name" : "a valid name");
  if (!triggerFilled) missing.push(form.triggerKind === "signal" ? "a signal type" : "a schedule");
  if (incompleteSteps > 0)
    missing.push(`${incompleteSteps} step${incompleteSteps > 1 ? "s" : ""} to be completed`);
  const ready = missing.length === 0;

  return (
    <div class="stack">
      <div class="section-header">
        <button type="button" class="btn btn-small" onClick={requestBack}>
          ← Back to built-in workflows
        </button>
      </div>

      <div class="callout">
        <strong>New workflow.</strong> Fill in the fields below to draft a custom business
        process. Each step maps to one governed ontology <code>ActionType</code>; you never write
        raw mutation logic. When you validate, the server checks the draft against the same rules
        the catalog loader uses and returns a ready-to-commit YAML. The console does not deploy it
        - you copy the YAML into <code>rule-catalog/workflows/</code> and open a PR, so review and
        rollback come for free. New workflows start in <span class="badge shadow">shadow</span>{" "}
        mode (judge and log, no changes) until a separate promotion PR.
      </div>

      <WorkflowSummary form={form} />

      {palette.length === 0 ? (
        <div class="empty error">
          <p class="mono">
            No ActionTypes are served on this deployment, so steps cannot be mapped. Wire the
            ActionType catalog (ReadApiConfig.workflow_authoring) to author workflows.
          </p>
        </div>
      ) : null}

      {/* Metadata */}
      <section class="stack-section">
        <h3 class="section-title">1. Workflow metadata</h3>
        <p class="muted small">
          <strong>Name</strong> is the stable id and audit key (lowercase dotted, e.g.{" "}
          <code>cost-aware-remediation</code>). <strong>Description</strong> is a one-line summary
          (&le; 200 chars).
        </p>
        <div class="form-grid">
          <label class="form-field">
            <span class="form-label">Name (dotted id)</span>
            <input
              ref={nameRef}
              id="wf-name"
              aria-describedby="wf-name-hint"
              class={form.name.trim() !== "" && !nameValid ? "form-input mono input-bad" : "form-input mono"}
              value={form.name}
              placeholder="cost-aware-remediation"
              onInput={(e) => patch({ name: (e.target as HTMLInputElement).value })}
            />
            <span
              id="wf-name-hint"
              class={form.name.trim() !== "" && !nameValid ? "field-hint hint-bad" : "field-hint"}
            >
              {form.name.trim() !== "" && !nameValid
                ? "Lowercase letters/digits/._- only, must start with a letter (max 80)."
                : "Lowercase dotted id, e.g. cost-aware-remediation."}
            </span>
          </label>
          <label class="form-field">
            <span class="form-label">Version</span>
            <input
              class="form-input mono"
              value={form.version}
              onInput={(e) => patch({ version: (e.target as HTMLInputElement).value })}
            />
          </label>
          <label class="form-field form-field-wide">
            <span class="form-label">Description (&le; 200 chars)</span>
            <input
              class="form-input"
              value={form.description}
              onInput={(e) => patch({ description: (e.target as HTMLInputElement).value })}
            />
          </label>
        </div>
      </section>

      {/* Trigger */}
      <section class="stack-section">
        <h3 class="section-title">2. Trigger</h3>
        <p class="muted small">
          When the workflow runs. <strong>Signal</strong> starts it when the control plane
          publishes a matching event (a <em>signal type</em>); <strong>schedule</strong> starts it
          on a cron expression. The signal type is <em>what happened</em> that should kick off the
          process - pick one of the detection signals below (e.g. <code>object.drift</code> = a
          resource drifted from its declared state), or choose <em>Custom</em> to type another.
        </p>
        <div class="form-grid">
          <label class="form-field">
            <span class="form-label">Kind</span>
            <select
              class="form-input"
              value={form.triggerKind}
              onChange={(e) =>
                patch({ triggerKind: (e.target as HTMLSelectElement).value as "signal" | "schedule" })
              }
            >
              <option value="signal">signal - run on an event</option>
              <option value="schedule">schedule - run on a cron</option>
            </select>
          </label>
          {form.triggerKind === "signal" ? (
            <SignalTypeField
              value={form.signalType}
              onChange={(v) => patch({ signalType: v })}
            />
          ) : (
            <label class="form-field">
              <span class="form-label">Schedule (cron)</span>
              <select
                class="form-input"
                value={SCHEDULE_PRESETS.some((p) => p.value === form.schedule) ? form.schedule : ""}
                onChange={(e) => {
                  const v = (e.target as HTMLSelectElement).value;
                  if (v) patch({ schedule: v });
                }}
              >
                <option value="">Presets...</option>
                {SCHEDULE_PRESETS.map((p) => (
                  <option value={p.value} key={p.value}>
                    {p.label} ({p.value})
                  </option>
                ))}
              </select>
              <input
                class="form-input mono"
                value={form.schedule}
                placeholder="0 3 * * 1"
                onInput={(e) => patch({ schedule: (e.target as HTMLInputElement).value })}
              />
              <span class="field-hint">Standard 5-field cron. Example: 0 3 * * 1 = 03:00 every Monday.</span>
            </label>
          )}
        </div>
      </section>

      {/* Steps */}
      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">3. Steps ({form.steps.length})</h3>
          <button type="button" class="btn btn-small" onClick={addStep}>
            + Add step
          </button>
        </div>
        <p class="muted small">
          The ordered actions the workflow runs. Each step maps to one ontology ActionType (pick
          from the dropdown) and inherits that action's four safety invariants (stop-condition,
          rollback, blast-radius cap, audit). Optional per step: a <strong>guard</strong> rule
          that gates it, a <strong>compensated by</strong> action that undoes it on rollback, and
          an <strong>on failure</strong> fallback (must be a later step). The card shows the
          selected action's safety posture.
        </p>
        <WorkflowFlow form={form} onSelect={selectStep} />
        <div class="stack">
          {form.steps.map((step, index) => {
            const at = paletteByName.get(step.action_type_ref);
            const laterIds = stepIds.slice(index + 1);
            const stepIncomplete = step.id.trim() === "" || step.action_type_ref.trim() === "";
            return (
              <Fragment key={step.key}>
                <div
                  id={`wf-step-${step.key}`}
                  class={stepIncomplete ? "step-card step-card-incomplete" : "step-card"}
                >
                  <div class="step-card-head">
                    <span class="badge">#{index + 1}</span>
                  <div class="step-move">
                    {stepIncomplete ? (
                      <span class="field-hint hint-bad">needs id + ActionType</span>
                    ) : null}
                    <button
                      type="button"
                      class="btn btn-small"
                      disabled={index === 0}
                      onClick={() => moveStep(index, -1)}
                      aria-label="Move step up"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      class="btn btn-small"
                      disabled={index === form.steps.length - 1}
                      onClick={() => moveStep(index, 1)}
                      aria-label="Move step down"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      class="btn btn-small btn-danger"
                      disabled={form.steps.length === 1}
                      onClick={() => removeStep(step.key)}
                      aria-label="Remove step"
                    >
                      Remove
                    </button>
                  </div>
                </div>
                <div class="form-grid">
                  <label class="form-field">
                    <span class="form-label">Step id</span>
                    <input
                      class="form-input mono"
                      value={step.id}
                      placeholder="annotate_cost"
                      onInput={(e) =>
                        patchStep(step.key, { id: (e.target as HTMLInputElement).value })
                      }
                    />
                  </label>
                  <label class="form-field">
                    <span class="form-label">Action to run</span>
                    <select
                      class="form-input mono"
                      value={step.action_type_ref}
                      onChange={(e) => {
                        const value = (e.target as HTMLSelectElement).value;
                        const fields: Partial<DraftStep> = { action_type_ref: value };
                        // Auto-suggest a step id when the operator has not set
                        // one yet, so picking an action is enough to get a valid
                        // step. Never clobber an id the operator already typed.
                        if (value && step.id.trim() === "") {
                          const taken = form.steps
                            .filter((s) => s.key !== step.key)
                            .map((s) => s.id.trim())
                            .filter(Boolean);
                          fields.id = suggestStepId(value, taken);
                        }
                        patchStep(step.key, fields);
                      }}
                    >
                      <option value="">(pick an action)</option>
                      <ActionTypeOptions grouped={groupedPalette} />
                    </select>
                  </label>
                </div>
                <details class="step-advanced">
                  <summary class="details-summary">
                    Advanced options (guard, rollback, on-failure) - optional
                  </summary>
                  <div class="form-grid">
                  <label class="form-field">
                    <span class="form-label">Guard rule ref (optional)</span>
                    <input
                      class="form-input mono"
                      value={step.guard_rule_ref}
                      onInput={(e) =>
                        patchStep(step.key, {
                          guard_rule_ref: (e.target as HTMLInputElement).value,
                        })
                      }
                    />
                  </label>
                  <label class="form-field">
                    <span class="form-label">Compensated by (optional)</span>
                    <select
                      class="form-input mono"
                      value={step.compensated_by}
                      onChange={(e) =>
                        patchStep(step.key, {
                          compensated_by: (e.target as HTMLSelectElement).value,
                        })
                      }
                    >
                      <option value="">(none)</option>
                      <ActionTypeOptions grouped={groupedPalette} />
                    </select>
                  </label>
                  <label class="form-field">
                    <span class="form-label">On failure (later step)</span>
                    <select
                      class="form-input mono"
                      value={step.on_failure}
                      onChange={(e) =>
                        patchStep(step.key, {
                          on_failure: (e.target as HTMLSelectElement).value,
                        })
                      }
                    >
                      <option value="">(none)</option>
                      {laterIds.map((id) => (
                        <option value={id} key={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </label>
                  </div>
                </details>
                {at ? <ActionTypeHint at={at} /> : null}
                </div>
                {index < form.steps.length - 1 ? (
                  <div class="step-connector" aria-hidden="true">
                    then ↓
                  </div>
                ) : null}
              </Fragment>
            );
          })}
        </div>
      </section>

      {/* Promotion gate (advanced - defaults are sensible, so this is
          collapsed by default to keep the first-run form short). */}
      <section class="stack-section">
        <details class="advanced-details">
          <summary>
            <span class="section-title">4. Promotion gate</span>{" "}
            <span class="muted small">(advanced - the defaults are fine for most workflows)</span>
          </summary>
          <p class="muted small">
            The bar the workflow must clear before it can be promoted from{" "}
            <span class="badge shadow">shadow</span> (judge and log, no mutation) to enforce.
            Promotion is always a separate governance PR that measures these thresholds - the
            builder only records them.
          </p>
          <div class="form-grid">
            <label class="form-field">
              <span class="form-label">Min shadow days</span>
              <input
                class="form-input mono"
                type="number"
                value={form.minShadowDays}
                onInput={(e) => patch({ minShadowDays: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Min samples</span>
              <input
                class="form-input mono"
                type="number"
                value={form.minSamples}
                onInput={(e) => patch({ minSamples: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Min accuracy</span>
              <input
                class="form-input mono"
                type="number"
                step="0.01"
                value={form.minAccuracy}
                onInput={(e) => patch({ minAccuracy: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Max policy escapes</span>
              <input
                class="form-input mono"
                type="number"
                value={form.maxPolicyEscapes}
                onInput={(e) => patch({ maxPolicyEscapes: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field form-field-wide">
              <span class="form-label">Anti-scope (optional)</span>
              <input
                class="form-input"
                value={form.antiScope}
                onInput={(e) => patch({ antiScope: (e.target as HTMLInputElement).value })}
              />
            </label>
          </div>
        </details>
      </section>

      {/* Validate + result */}
      <section class="stack-section" ref={resultRef}>
        <div class="section-header">
          <h3 class="section-title">5. Validate &amp; export</h3>
          <div class="code-actions">
            <button type="button" class="btn btn-small" onClick={resetForm} disabled={validating}>
              Reset
            </button>
            <button
              type="button"
              class="btn"
              onClick={onValidate}
              disabled={validating || !ready}
            >
              {validating ? "Validating..." : "Validate draft"}
            </button>
          </div>
        </div>
        <p class="muted small">
          Runs the draft through the server-side workflow validator. If anything is wrong you get a
          list of exactly what and where; if it passes you get a canonical YAML to copy into a
          <code> rule-catalog/workflows/&lt;name&gt;.yaml</code> file and open as a PR.
        </p>
        {!ready ? (
          <p class="field-hint hint-bad" role="status">
            Before validating, add {missing.join(", ")}.
          </p>
        ) : null}
        {transportError ? (
          <div class="empty error" role="alert">
            <p class="mono">{transportError}</p>
          </div>
        ) : null}
        <div aria-live="polite">
          {result ? <ValidationResult result={result} name={form.name} /> : null}
        </div>
      </section>
    </div>
  );
}

/** Render the ActionType palette as category-grouped <optgroup>s for a
 * step dropdown. Shared by the action_type_ref and compensated_by selects. */
function ActionTypeOptions({
  grouped,
}: {
  readonly grouped: readonly (readonly [string, readonly ActionTypePaletteEntry[]])[];
}) {
  return (
    <>
      {grouped.map(([cat, entries]) => (
        <optgroup label={cat} key={cat}>
          {entries.map((p) => (
            <option value={p.name} key={p.name}>
              {humanizeActionName(p.name)} ({p.name})
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

function ActionTypeHint({ at }: { readonly at: ActionTypePaletteEntry }) {
  return (
    <div class="at-hint">
      <strong>{humanizeActionName(at.name)}</strong>
      <span class="mono muted">{at.name}</span>
      <span class="badge">{at.category ?? at.operation}</span>
      <span class="mono muted">rollback: {at.rollback_contract}</span>
      {at.irreversible ? <span class="badge hil">irreversible</span> : null}
      {at.hil_tiers.length > 0 ? (
        <span class="badge hil" title="Needs a human approval at this tier">
          needs approval @ {at.hil_tiers.join(", ")}
        </span>
      ) : null}
      {at.description ? <span class="muted small">{at.description}</span> : null}
    </div>
  );
}

/** Signal-type picker: a dropdown of the control plane's detection
 * signals plus a Custom escape hatch (the field is a free string
 * server-side). Shows the selected signal's plain-language meaning. */
function SignalTypeField({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (v: string) => void;
}) {
  const isKnown = KNOWN_SIGNAL_VALUES.has(value);
  const selectValue = isKnown ? value : CUSTOM_SIGNAL;
  const activeHint = SIGNAL_TYPE_OPTIONS.find((o) => o.value === value)?.hint;
  return (
    <label class="form-field">
      <span class="form-label">What starts it (signal)</span>
      <select
        class="form-input"
        value={selectValue}
        onChange={(e) => {
          const v = (e.target as HTMLSelectElement).value;
          onChange(v === CUSTOM_SIGNAL ? "" : v);
        }}
      >
        {SIGNAL_TYPE_OPTIONS.map((o) => (
          <option value={o.value} key={o.value}>
            {o.label} ({o.value})
          </option>
        ))}
        <option value={CUSTOM_SIGNAL}>Custom (type your own)...</option>
      </select>
      {selectValue === CUSTOM_SIGNAL ? (
        <input
          class="form-input mono"
          value={value}
          placeholder="object.my-signal"
          onInput={(e) => onChange((e.target as HTMLInputElement).value)}
        />
      ) : null}
      <span class="field-hint">
        {activeHint ?? "A custom event type the control plane publishes (object.<kebab-name>)."}
      </span>
    </label>
  );
}

function ValidationResult({
  result,
  name,
}: {
  readonly result: ValidateResponse;
  readonly name: string;
}) {
  if (!result.valid) {
    return (
      <div class="stack">
        <div class="badge deny">{result.issues.length} issue(s) - not yet valid</div>
        <div class="scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Where</th>
                <th>Problem</th>
              </tr>
            </thead>
            <tbody>
              {result.issues.map((issue, i) => (
                <tr key={i}>
                  <td class="mono" title={issue.key}>
                    {humanizeIssueKey(issue.key)}
                  </td>
                  <td>{issue.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  const fileName = `${name.trim() || "workflow"}.yaml`;
  const yaml = result.yaml_preview ?? "";
  const filePath = `rule-catalog/workflows/${fileName}`;
  const prUrl = githubNewFileUrl(filePath, yaml);
  function download(): void {
    const blob = new Blob([yaml], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
    // Revoke after a tick so the download has started (immediate revoke can
    // cancel it in some browsers).
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div class="stack">
      <div class="badge enforce">Valid - ready for a remediation PR</div>
      <p class="muted small">
        {prUrl
          ? "Your draft is valid. Open a pull request to propose it - the console never commits, so review, audit, and rollback come for free."
          : null}
        {prUrl ? null : (
          <>
            Copy this into <code class="mono">{filePath}</code> and open a remediation PR. The
            console does not commit - authoring stays git-native so audit, review, and rollback
            come for free.
          </>
        )}
      </p>
      <div class="code-actions">
        {prUrl ? (
          <a class="btn" href={prUrl} target="_blank" rel="noopener noreferrer">
            Open a PR on GitHub →
          </a>
        ) : null}
        <CopyButton text={yaml} label="Copy YAML" />
        <button type="button" class="btn btn-small" onClick={download}>
          Download {fileName}
        </button>
      </div>
      {prUrl ? (
        <p class="field-hint">
          Opens GitHub in a new tab with <code class="mono">{filePath}</code> pre-filled. Review,
          then "Propose new file" to create the PR.
        </p>
      ) : null}
      <pre class="mono scroll code-block">{yaml}</pre>
    </div>
  );
}
