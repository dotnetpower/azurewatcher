import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { visibleNavigationGroups } from "./navigation-shell";
import { TOOLTIP_DELAY_MS, TOOLTIP_EXIT_MS } from "./tooltip";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const source = readFileSync(fileURLToPath(new URL("./navigation-shell.tsx", import.meta.url)), "utf8");

describe("navigation shell groups", () => {
  test("shows Labs only in development mode", () => {
    expect(visibleNavigationGroups(false).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence", "settings",
    ]);
    expect(visibleNavigationGroups(true).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence", "labs", "settings",
    ]);
  });

  test("keeps the mobile command deck launcher clear of the activity rail", () => {
    expect(styles).not.toContain(".deck-invoke,\n  .deck-overlay { left: 0; }");
    expect(styles).toContain(".deck-invoke { left: var(--rail-width); }");
    expect(styles).toContain(
      "height: calc(100dvh - var(--header-height) - var(--deck-invoke-height));",
    );
    expect(styles).toContain(".shell-body > main");
  });

  test("uses the shared portal tooltip instead of native activity-bar titles", () => {
    expect(source).toContain('<Tooltip content={label} placement="right">');
    expect(source).toContain('<Tooltip content={panel.label} placement="right">');
    expect(source).not.toContain("title=");
    expect(styles).toContain('.app-tooltip[data-state="delayed-open"]');
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
  });

  test("keeps pointer entry deliberate and tooltip exit fast", () => {
    expect(TOOLTIP_DELAY_MS).toBe(100);
    expect(TOOLTIP_EXIT_MS).toBe(50);
  });
});
