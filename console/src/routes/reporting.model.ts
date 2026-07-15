import { decodeRenderedWidget, type RenderedWidget } from "./processes.model";

export interface ReportVariable {
  readonly name: string;
  readonly default: string | null;
  readonly values: readonly string[];
  readonly description: string;
}

export interface ReportSummary {
  readonly id: string;
  readonly version: string;
  readonly name: string;
  readonly description: string;
  readonly tags: readonly string[];
  readonly widget_count: number;
  readonly variables: readonly ReportVariable[];
}

export interface ReportList {
  readonly items: readonly ReportSummary[];
  readonly formats: readonly string[];
}

export interface ReportingRegistry {
  readonly datasources: readonly string[];
  readonly widgets: readonly string[];
  readonly formats: readonly string[];
}

export interface RenderedReportView {
  readonly id: string;
  readonly version: string;
  readonly name: string;
  readonly description: string;
  readonly generated_at: string;
  readonly time_range: Readonly<Record<string, unknown>>;
  readonly variables: Readonly<Record<string, string>>;
  readonly widgets: readonly RenderedWidget[];
  readonly tags: readonly string[];
}

export function decodeReportList(value: unknown): ReportList {
  const root = record(value, "report list");
  return {
    items: array(root["items"], "report list.items").map((item, index) =>
      decodeReportSummary(item, `report list.items[${index}]`),
    ),
    formats: stringArray(root["formats"], "report list.formats"),
  };
}

export function decodeReportingRegistry(value: unknown): ReportingRegistry {
  const root = record(value, "reporting registry");
  return {
    datasources: stringArray(root["datasources"], "reporting registry.datasources"),
    widgets: stringArray(root["widgets"], "reporting registry.widgets"),
    formats: stringArray(root["formats"], "reporting registry.formats"),
  };
}

export function decodeRenderedReport(value: unknown): RenderedReportView {
  const root = record(value, "rendered report");
  return {
    id: stringField(root, "id", "rendered report"),
    version: stringField(root, "version", "rendered report"),
    name: stringField(root, "name", "rendered report"),
    description: stringField(root, "description", "rendered report"),
    generated_at: stringField(root, "generated_at", "rendered report"),
    time_range: record(root["time_range"], "rendered report.time_range"),
    variables: stringRecord(root["variables"], "rendered report.variables"),
    widgets: array(root["widgets"], "rendered report.widgets").map((widget, index) =>
      decodeRenderedWidget(widget, `rendered report.widgets[${index}]`),
    ),
    tags: stringArray(root["tags"], "rendered report.tags"),
  };
}

function decodeReportSummary(value: unknown, label: string): ReportSummary {
  const item = record(value, label);
  return {
    id: stringField(item, "id", label),
    version: stringField(item, "version", label),
    name: stringField(item, "name", label),
    description: stringField(item, "description", label),
    tags: stringArray(item["tags"], `${label}.tags`),
    widget_count: nonNegativeInteger(item, "widget_count", label),
    variables: array(item["variables"], `${label}.variables`).map((raw, index) => {
      const variable = record(raw, `${label}.variables[${index}]`);
      const defaultValue = variable["default"];
      return {
        name: stringField(variable, "name", "report variable"),
        default: defaultValue === null ? null : String(defaultValue),
        values: stringArray(variable["values"], "report variable.values"),
        description: stringField(variable, "description", "report variable"),
      };
    }),
  };
}

function contractError(message: string): Error {
  return new Error(`invalid reporting response: ${message}`);
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw contractError(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw contractError(`${label} MUST be an array`);
  return value;
}

function stringField(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw contractError(`${label}.${key} MUST be a string`);
  return value[key];
}

function stringArray(value: unknown, label: string): readonly string[] {
  const items = array(value, label);
  if (items.some((item) => typeof item !== "string")) {
    throw contractError(`${label} MUST contain strings`);
  }
  return items as readonly string[];
}

function stringRecord(value: unknown, label: string): Readonly<Record<string, string>> {
  const item = record(value, label);
  if (Object.values(item).some((entry) => typeof entry !== "string")) {
    throw contractError(`${label} MUST contain string values`);
  }
  return item as Readonly<Record<string, string>>;
}

function nonNegativeInteger(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const item = value[key];
  if (typeof item !== "number" || !Number.isInteger(item) || item < 0) {
    throw contractError(`${label}.${key} MUST be a non-negative integer`);
  }
  return item;
}
