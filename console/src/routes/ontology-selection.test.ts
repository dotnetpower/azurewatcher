import { describe, expect, it } from "vitest";
import { ontologyNamedSelection } from "./ontology";
import {
  ontologyActionFiltersFromSearch,
  ontologyActionHref,
  requestedOntologyAction,
  resolveOntologyActionSelection,
} from "./ontology-actions";
import type { OntologyActionTypeRecord } from "./ontology.types";

function action(name: string): OntologyActionTypeRecord {
  return { name } as OntologyActionTypeRecord;
}

describe("ontology explicit selections", () => {
  it("keeps an absent ActionType selection implicit", () => {
    expect(requestedOntologyAction(new URLSearchParams())).toBeNull();
    expect(requestedOntologyAction(new URLSearchParams("action=alpha"))).toBe("alpha");
  });

  it("defaults only when no LinkType or ActionType was requested", () => {
    expect(ontologyNamedSelection(["alpha", "beta"], null)).toBe("alpha");
    expect(ontologyNamedSelection(["alpha", "beta"], "missing")).toBe("missing");
  });

  it("never substitutes another ActionType for an invalid or filtered selection", () => {
    const alpha = action("alpha");
    const beta = action("beta");
    expect(resolveOntologyActionSelection([alpha, beta], [alpha, beta], null)).toBe(alpha);
    expect(resolveOntologyActionSelection([alpha, beta], [alpha, beta], "missing")).toBeNull();
    expect(resolveOntologyActionSelection([alpha, beta], [beta], "alpha")).toBeNull();
  });

  it("round-trips ActionType filters through selection links", () => {
    const filters = ontologyActionFiltersFromSearch(new URLSearchParams(
      "q=restart&category=ops&trigger=operator_request&execution=direct_api",
    ));

    expect(filters).toEqual({
      query: "restart",
      category: "ops",
      trigger: "operator_request",
      execution: "direct_api",
    });
    expect(ontologyActionHref(filters, "restart-service")).toBe(
      "/ontology?view=actions&action=restart-service&q=restart&category=ops&trigger=operator_request&execution=direct_api",
    );
  });

  it("omits default ActionType filters from the canonical URL", () => {
    const filters = ontologyActionFiltersFromSearch(new URLSearchParams());

    expect(ontologyActionHref(filters, null)).toBe("/ontology?view=actions");
  });
});
