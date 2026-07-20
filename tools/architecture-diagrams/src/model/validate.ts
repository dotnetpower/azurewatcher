import type { ErrorObject } from "ajv";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

import type { DiagramSpec } from "./types.js";

const schemaPath = fileURLToPath(
  new URL("../../schema/diagram.schema.json", import.meta.url),
);
const schema = JSON.parse(await readFile(schemaPath, "utf8")) as object;
const require = createRequire(import.meta.url);
const AjvConstructor = require("ajv") as typeof import("ajv").default;
const addFormats = require("ajv-formats") as typeof import("ajv-formats").default;
const ajv = new AjvConstructor({ allErrors: true, strict: true });
addFormats(ajv);
const validateSchema = ajv.compile<DiagramSpec>(schema);

function formatSchemaErrors(errors: ErrorObject[] | null | undefined): string {
  return (errors ?? [])
    .map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
    .join("; ");
}

function endpointNodeId(endpoint: string): string {
  return endpoint.split(":", 1)[0] ?? endpoint;
}

function findDuplicate(values: string[]): string | undefined {
  const seen = new Set<string>();
  return values.find((value) => {
    if (seen.has(value)) return true;
    seen.add(value);
    return false;
  });
}

export function validateDiagram(value: unknown): DiagramSpec {
  if (!validateSchema(value)) {
    throw new Error(`Diagram schema validation failed: ${formatSchemaErrors(validateSchema.errors)}`);
  }

  const spec = value as DiagramSpec;
  const elementIds = [...spec.groups.map((group) => group.id), ...spec.nodes.map((node) => node.id)];
  const duplicateElement = findDuplicate(elementIds);
  if (duplicateElement) {
    throw new Error(`Duplicate diagram element id: ${duplicateElement}`);
  }

  const duplicateEdge = findDuplicate(spec.edges.map((edge) => edge.id));
  if (duplicateEdge) {
    throw new Error(`Duplicate diagram edge id: ${duplicateEdge}`);
  }

  const groupIds = new Set(spec.groups.map((group) => group.id));
  for (const element of [...spec.groups, ...spec.nodes]) {
    if (element.parent && !groupIds.has(element.parent)) {
      throw new Error(`Unknown parent group '${element.parent}' on '${element.id}'`);
    }
  }

  const nodeIds = new Set(spec.nodes.map((node) => node.id));
  for (const edge of spec.edges) {
    for (const endpoint of [edge.from, edge.to]) {
      const nodeId = endpointNodeId(endpoint);
      if (!nodeIds.has(nodeId)) {
        throw new Error(`Unknown edge endpoint '${endpoint}' on '${edge.id}'`);
      }
    }
  }

  return spec;
}

export function parseDiagram(source: string): DiagramSpec {
  return validateDiagram(parse(source));
}
