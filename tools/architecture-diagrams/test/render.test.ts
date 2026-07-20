import assert from "node:assert/strict";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const source = `
id: render-sample
version: 1
kind: container
locales:
  en: { title: Render sample, description: Layout check, alt: A source sends an event to a processor. }
  ko: { title: Render sample, description: Layout check, alt: Source가 processor로 event를 보냅니다. }
canvas: { width: 800, height: 480, direction: RIGHT }
groups:
  - id: core
    kind: system
    label: { en: Core, ko: Core }
nodes:
  - id: source
    kind: external
    label: { en: Source, ko: Source }
  - id: processor
    parent: core
    kind: process
    label: { en: Processor, ko: Processor }
edges:
  - id: event-flow
    from: source
    to: processor
    kind: event
    label: { en: normalized event, ko: normalized event }
legend:
  - kind: event
    label: { en: Asynchronous event, ko: Asynchronous event }
`;

test("lays out nested groups and renders accessible SVG", async () => {
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.ok(layout.groups.get("core")?.width);
  assert.ok(layout.nodes.get("processor")?.x);
  assert.match(svg, /<svg[^>]+role="img"/);
  assert.match(svg, /<title id="diagram-title">Render sample<\/title>/);
  assert.match(svg, /data-node-id="processor"/);
  assert.match(svg, /marker-end="url\(#arrow-event\)"/);
});
