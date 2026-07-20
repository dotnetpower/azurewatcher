import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { checkArtifacts, compileDiagram, writeArtifacts } from "./compiler.js";
import { parseDiagram } from "./model/validate.js";

const command = process.argv[2] ?? "validate";
const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const sourceDirectory = path.join(repositoryRoot, "docs/diagrams");
const outputDirectory = path.join(repositoryRoot, "site/public/diagrams");

async function diagramPaths(): Promise<string[]> {
  return (await readdir(sourceDirectory))
    .filter((name) => name.endsWith(".diagram.yaml"))
    .sort()
    .map((name) => path.join(sourceDirectory, name));
}

async function run(): Promise<void> {
  const sources = await diagramPaths();
  if (!sources.length) throw new Error(`No diagram specifications found in ${sourceDirectory}`);
  const specs = await Promise.all(
    sources.map(async (sourcePath) => parseDiagram(await readFile(sourcePath, "utf8"))),
  );

  if (command === "validate") {
    console.log(`Validated ${specs.length} architecture diagram specification(s).`);
    return;
  }
  if (command !== "render" && command !== "check") {
    throw new Error(`Unknown command '${command}'. Use validate, render, or check.`);
  }

  const artifacts = (await Promise.all(specs.map(compileDiagram))).flat();
  if (command === "render") {
    await writeArtifacts(outputDirectory, artifacts);
    console.log(`Rendered ${artifacts.length} artifact(s) to ${outputDirectory}.`);
    return;
  }

  const stale = await checkArtifacts(outputDirectory, artifacts);
  if (stale.length) {
    throw new Error(`Generated diagram artifacts are stale: ${stale.join(", ")}`);
  }
  console.log(`Checked ${artifacts.length} generated architecture diagram artifact(s).`);
}

run().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
