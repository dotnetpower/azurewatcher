/**
 * Shared UI primitives for panel routes.
 *
 * Each component here has ONE responsibility so panel modules can stay
 * focused on data-fetching + composition. The primitives are read-only:
 * they never issue privileged calls, matching the console contract in
 * app-shape.instructions.md § Operator console.
 */

import type { ComponentChildren, JSX } from "preact";

// ---------------------------------------------------------------------------
// PageHeader - page identity (title + optional subtitle + optional actions)
// ---------------------------------------------------------------------------

export interface PageHeaderProps {
  readonly title: string;
  readonly subtitle?: ComponentChildren;
  readonly actions?: ComponentChildren;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <header class="page-header">
      <div class="page-header-text">
        <h2 class="page-header-title">{title}</h2>
        {subtitle ? <p class="page-header-subtitle muted">{subtitle}</p> : null}
      </div>
      {actions ? <div class="page-header-actions">{actions}</div> : null}
    </header>
  );
}

// ---------------------------------------------------------------------------
// AsyncBoundary - render loading / error / ready in a single primitive
// ---------------------------------------------------------------------------

export type AsyncState<T> =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

export interface AsyncBoundaryProps<T> {
  readonly state: AsyncState<T>;
  /** Label describing what is loading, e.g. "audit log". */
  readonly resourceLabel: string;
  /** Optional custom idle view; defaults to the ready renderer being skipped. */
  readonly idle?: ComponentChildren;
  readonly children: (data: T) => JSX.Element;
}

export function AsyncBoundary<T>({
  state,
  resourceLabel,
  idle,
  children,
}: AsyncBoundaryProps<T>) {
  if (state.status === "idle") {
    return <>{idle ?? null}</>;
  }
  if (state.status === "loading") {
    return <LoadingState label={`Loading ${resourceLabel}...`} />;
  }
  if (state.status === "unavailable") {
    return <UnavailableState message={state.message} />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        message={`Failed to load ${resourceLabel}: ${state.message}`}
      />
    );
  }
  return children(state.data);
}

// ---------------------------------------------------------------------------
// LoadingState / ErrorState / EmptyState / UnavailableState
// ---------------------------------------------------------------------------

export function LoadingState({ label = "Loading..." }: { readonly label?: string }) {
  return (
    <div class="state-block state-loading" role="status" aria-live="polite">
      <span class="state-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message }: { readonly message: string }) {
  return (
    <div class="state-block state-error" role="alert">
      <span class="state-icon" aria-hidden="true">!</span>
      <span>{message}</span>
    </div>
  );
}

export interface EmptyStateProps {
  readonly title: string;
  readonly body?: ComponentChildren;
}

export function EmptyState({ title, body }: EmptyStateProps) {
  return (
    <div class="state-block state-empty">
      <span class="state-icon" aria-hidden="true">–</span>
      <div>
        <div class="state-empty-title">{title}</div>
        {body ? <div class="state-empty-body muted">{body}</div> : null}
      </div>
    </div>
  );
}

export function UnavailableState({ message }: { readonly message: string }) {
  return (
    <div class="state-block state-unavailable">
      <span class="state-icon" aria-hidden="true">?</span>
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KpiCard / KpiGrid - single-metric display, horizontal layout
// ---------------------------------------------------------------------------

export interface KpiCardProps {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint?: ComponentChildren;
  readonly tone?: "default" | "positive" | "warning" | "danger";
}

export function KpiCard({ label, value, hint, tone = "default" }: KpiCardProps) {
  return (
    <div class={`card kpi-card kpi-tone-${tone}`}>
      <span class="kpi-card-label">{label}</span>
      <span class="kpi-card-value">{value}</span>
      {hint ? <span class="kpi-card-hint muted">{hint}</span> : null}
    </div>
  );
}

export function KpiGrid({ children }: { readonly children: ComponentChildren }) {
  return <section class="kpi-grid">{children}</section>;
}

// ---------------------------------------------------------------------------
// DataTable - tabular render + key management
// ---------------------------------------------------------------------------

export interface Column<Row> {
  readonly key: string;
  readonly header: ComponentChildren;
  readonly render: (row: Row) => ComponentChildren;
  /** CSS class applied to the cell, e.g. `"mono"`, `"num"`. */
  readonly cellClass?: string;
  /** CSS class applied to the header cell. */
  readonly headerClass?: string;
}

export interface DataTableProps<Row> {
  readonly columns: readonly Column<Row>[];
  readonly rows: readonly Row[];
  readonly keyOf: (row: Row, index: number) => string | number;
  readonly empty?: ComponentChildren;
  readonly caption?: ComponentChildren;
}

export function DataTable<Row>({
  columns,
  rows,
  keyOf,
  empty,
  caption,
}: DataTableProps<Row>) {
  if (rows.length === 0) {
    return (
      <div class="data-table-empty muted">{empty ?? "No rows to display."}</div>
    );
  }
  return (
    <div class="data-table-wrap">
      <table class="data-table">
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} class={c.headerClass}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)}>
              {columns.map((c) => (
                <td key={c.key} class={c.cellClass}>{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatusPill - colored status chip
// ---------------------------------------------------------------------------

export type PillKind =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "shadow"
  | "enforce"
  | "hil"
  | "auto";

export interface StatusPillProps {
  readonly kind: PillKind;
  readonly label: ComponentChildren;
  readonly title?: string;
}

export function StatusPill({ kind, label, title }: StatusPillProps) {
  return (
    <span class={`status-pill status-pill-${kind}`} title={title}>
      {label}
    </span>
  );
}
