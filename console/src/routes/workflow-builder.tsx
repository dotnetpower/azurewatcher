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
 */

import { useEffect, useMemo, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { t } from "../i18n";
import {
  type ActionTypePaletteEntry,
  type ActionTypePaletteResponse,
  type ValidateResponse,
  validateWorkflowDraft,
} from "../workflow/validate";

interface Props {
  readonly client: ReadApiClient;
}

interface DraftStep {
  readonly key: number;
  id: string;
  action_type_ref: string;
  guard_rule_ref: string;
  compensated_by: string;
  on_failure: string;
}

interface FormState {
  name: string;
  version: string;
  description: string;
  triggerKind: "signal" | "schedule";
  signalType: string;
  schedule: string;
  minShadowDays: string;
  minSamples: string;
  minAccuracy: string;
  maxPolicyEscapes: string;
  antiScope: string;
  steps: DraftStep[];
}

function emptyStep(key: number): DraftStep {
  return { key, id: "", action_type_ref: "", guard_rule_ref: "", compensated_by: "", on_failure: "" };
}

const INITIAL_FORM: FormState = {
  name: "",
  version: "1.0.0",
  description: "",
  triggerKind: "signal",
  signalType: "object.drift",
  schedule: "",
  minShadowDays: "14",
  minSamples: "100",
  minAccuracy: "0.95",
  maxPolicyEscapes: "0",
  antiScope: "",
  steps: [emptyStep(0)],
};

/** Assemble the JSON draft the validate endpoint expects, dropping empty
 * optional fields so the server sees a clean mapping. */
function buildDraft(form: FormState): Record<string, unknown> {
  const trigger: Record<string, unknown> = { kind: form.triggerKind };
  if (form.triggerKind === "signal") trigger["signal_type"] = form.signalType.trim();
  else trigger["schedule"] = form.schedule.trim();

  const steps = form.steps.map((s) => {
    const step: Record<string, unknown> = {
      id: s.id.trim(),
      action_type_ref: s.action_type_ref.trim(),
    };
    if (s.guard_rule_ref.trim()) step["guard_rule_ref"] = s.guard_rule_ref.trim();
    if (s.compensated_by.trim()) step["compensated_by"] = s.compensated_by.trim();
    if (s.on_failure.trim()) step["on_failure"] = s.on_failure.trim();
    return step;
  });

  const draft: Record<string, unknown> = {
    schema_version: "1.0.0",
    name: form.name.trim(),
    version: form.version.trim(),
    trigger,
    default_mode: "shadow",
    promotion_gate: {
      min_shadow_days: Number(form.minShadowDays),
      min_samples: Number(form.minSamples),
      min_accuracy: Number(form.minAccuracy),
      max_policy_escapes: Number(form.maxPolicyEscapes),
    },
    steps,
  };
  if (form.description.trim()) draft["description"] = form.description.trim();
  if (form.antiScope.trim()) draft["anti_scope"] = form.antiScope.trim();
  return draft;
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<ActionTypePaletteResponse>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = await client.panel<ActionTypePaletteResponse>("/workflows/action-types");
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes("404")) {
            setState({
              status: "unavailable",
              message:
                "The workflow authoring route is not wired on this deployment. " +
                "Set ReadApiConfig.workflow_authoring in the composition root to enable it.",
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
        {(data) => <BuilderBody palette={data.action_types} />}
      </AsyncBoundary>
    </div>
  );
}

function BuilderBody({ palette }: { readonly palette: readonly ActionTypePaletteEntry[] }) {
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [nextKey, setNextKey] = useState(1);
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [validating, setValidating] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);

  usePublishViewContext(
    () => ({
      routeId: "workflow-builder",
      routeLabel: "Workflow builder",
      headline: `${palette.length} ActionTypes - ${form.steps.length} steps drafted`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "palette_size", value: palette.length, group: "workflow" },
        { key: "step_count", value: form.steps.length, group: "workflow" },
        { key: "workflow_name", value: form.name || "(unnamed)", group: "workflow" },
      ],
    }),
    [palette.length, form.steps.length, form.name],
  );

  const paletteByName = useMemo(
    () => new Map(palette.map((p) => [p.name, p])),
    [palette],
  );

  function patch(fields: Partial<FormState>): void {
    setForm((prev) => ({ ...prev, ...fields }));
    setResult(null);
  }

  function patchStep(key: number, fields: Partial<DraftStep>): void {
    setForm((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => (s.key === key ? { ...s, ...fields } : s)),
    }));
    setResult(null);
  }

  function addStep(): void {
    setForm((prev) => ({ ...prev, steps: [...prev.steps, emptyStep(nextKey)] }));
    setNextKey((k) => k + 1);
    setResult(null);
  }

  function removeStep(key: number): void {
    setForm((prev) => ({ ...prev, steps: prev.steps.filter((s) => s.key !== key) }));
    setResult(null);
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
    setResult(null);
  }

  async function onValidate(): Promise<void> {
    setValidating(true);
    setTransportError(null);
    setResult(null);
    try {
      const res = await validateWorkflowDraft(buildDraft(form));
      setResult(res);
    } catch (err) {
      setTransportError(err instanceof Error ? err.message : String(err));
    } finally {
      setValidating(false);
    }
  }

  const stepIds = form.steps.map((s) => s.id.trim()).filter(Boolean);

  return (
    <div class="stack">
      {/* Metadata */}
      <section class="stack-section">
        <h3 class="section-title">Workflow metadata</h3>
        <div class="form-grid">
          <label class="form-field">
            <span class="form-label">Name (dotted id)</span>
            <input
              class="form-input mono"
              value={form.name}
              placeholder="cost-aware-remediation"
              onInput={(e) => patch({ name: (e.target as HTMLInputElement).value })}
            />
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
        <h3 class="section-title">Trigger</h3>
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
              <option value="signal">signal</option>
              <option value="schedule">schedule</option>
            </select>
          </label>
          {form.triggerKind === "signal" ? (
            <label class="form-field">
              <span class="form-label">Signal type</span>
              <input
                class="form-input mono"
                value={form.signalType}
                placeholder="object.drift"
                onInput={(e) => patch({ signalType: (e.target as HTMLInputElement).value })}
              />
            </label>
          ) : (
            <label class="form-field">
              <span class="form-label">Schedule (cron)</span>
              <input
                class="form-input mono"
                value={form.schedule}
                placeholder="0 3 * * 1"
                onInput={(e) => patch({ schedule: (e.target as HTMLInputElement).value })}
              />
            </label>
          )}
        </div>
      </section>

      {/* Steps */}
      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Steps ({form.steps.length})</h3>
          <button type="button" class="btn btn-small" onClick={addStep}>
            + Add step
          </button>
        </div>
        <p class="muted small">
          Each step maps to one ontology ActionType; it inherits that action's four safety
          invariants (stop-condition, rollback, blast-radius cap, audit). An
          <code> on_failure</code> target must be a later step.
        </p>
        <div class="stack">
          {form.steps.map((step, index) => {
            const at = paletteByName.get(step.action_type_ref);
            const laterIds = stepIds.slice(index + 1);
            return (
              <div class="step-card" key={step.key}>
                <div class="step-card-head">
                  <span class="badge">#{index + 1}</span>
                  <div class="step-move">
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
                    <span class="form-label">ActionType</span>
                    <select
                      class="form-input mono"
                      value={step.action_type_ref}
                      onChange={(e) =>
                        patchStep(step.key, {
                          action_type_ref: (e.target as HTMLSelectElement).value,
                        })
                      }
                    >
                      <option value="">(select an ActionType)</option>
                      {palette.map((p) => (
                        <option value={p.name} key={p.name}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
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
                      {palette.map((p) => (
                        <option value={p.name} key={p.name}>
                          {p.name}
                        </option>
                      ))}
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
                {at ? <ActionTypeHint at={at} /> : null}
              </div>
            );
          })}
        </div>
      </section>

      {/* Promotion gate */}
      <section class="stack-section">
        <h3 class="section-title">Promotion gate</h3>
        <p class="muted small">
          New workflows ship in <span class="badge shadow">shadow</span> mode (judge and log,
          no mutation). Promotion to enforce is a separate governance PR that measures this
          gate.
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
      </section>

      {/* Validate + result */}
      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Validate &amp; export</h3>
          <button type="button" class="btn" onClick={onValidate} disabled={validating}>
            {validating ? "Validating..." : "Validate draft"}
          </button>
        </div>
        {transportError ? <div class="empty error"><p class="mono">{transportError}</p></div> : null}
        {result ? <ValidationResult result={result} name={form.name} /> : null}
      </section>
    </div>
  );
}

function ActionTypeHint({ at }: { readonly at: ActionTypePaletteEntry }) {
  return (
    <div class="at-hint">
      <span class="badge">{at.category ?? at.operation}</span>
      <span class="mono muted">rollback: {at.rollback_contract}</span>
      {at.irreversible ? <span class="badge hil">irreversible</span> : null}
      {at.hil_tiers.length > 0 ? (
        <span class="badge hil">HIL @ {at.hil_tiers.join(", ")}</span>
      ) : null}
      {at.description ? <span class="muted small">{at.description}</span> : null}
    </div>
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
                  <td class="mono">{issue.key}</td>
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
  return (
    <div class="stack">
      <div class="badge enforce">Valid - ready for a remediation PR</div>
      <p class="muted small">
        Copy this into <code class="mono">rule-catalog/workflows/{fileName}</code> and open a
        remediation PR. The console does not commit - authoring stays git-native so audit,
        review, and rollback come for free.
      </p>
      <div class="code-actions">
        <CopyButton text={yaml} label="Copy YAML" />
      </div>
      <pre class="mono scroll code-block">{yaml}</pre>
    </div>
  );
}
