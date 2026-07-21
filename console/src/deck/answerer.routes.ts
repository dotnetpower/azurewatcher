/**
 * Deterministic answerer per-route enhancers - one function per screen
 * that turns a query + snapshot into a domain-specific `Answer`.
 *
 * SRP: route-specific matching only. Snapshot lookups come from
 * `answerer.helpers.ts`; static data from `answerer.catalogs.ts`;
 * upstream pipeline stages (glossary / list / causal / meta) run in
 * `answerer.resolvers.ts` before dispatch reaches these enhancers.
 *
 * Each function receives a lowercased `q` and the snapshot the
 * screen published; the main dispatcher in `answerer.ts` fans out on
 * `snapshot.routeId`.
 */

import type { ViewSnapshot } from "./context";
import type { Answer } from "./answerer.catalogs";
import {
  defaultFollowUps,
  factToCitation,
  findFact,
} from "./answerer.helpers";

// ---------------------------------------------------------------------------
// Live cockpit
// ---------------------------------------------------------------------------

export function answerLive(q: string, snapshot: ViewSnapshot): Answer {
  const tiles = (snapshot.records?.tiles ?? []) as readonly Record<string, unknown>[];
  const attention = findFact(snapshot, "attention.total") ?? 0;

  if (/attention|need.*(look|action)|urgent/.test(q)) {
    const hil = findFact(snapshot, "attention.hil") ?? 0;
    const deny = findFact(snapshot, "attention.deny") ?? 0;
    const failed = findFact(snapshot, "attention.failed") ?? 0;
    const stuck = findFact(snapshot, "attention.stuck") ?? 0;
    return {
      text:
        Number(attention) === 0
          ? "No attention needed. Autonomy is holding: 0 approvals, 0 deny, 0 failed, 0 stuck."
          : `${attention} items need attention: ${hil} approvals waiting, ${deny} denied, ${failed} failed, ${stuck} stuck (>20s without reaching audit).`,
      citations: [
        { label: "Approvals", value: String(hil) },
        { label: "Deny", value: String(deny) },
        { label: "Failed", value: String(failed) },
        { label: "Stuck", value: String(stuck) },
      ],
      followUps: ["which tiles are failed?", "which are stuck?"],
    };
  }

  if (/vertical|change|resilience|cost/.test(q)) {
    const change = findFact(snapshot, "verticals.change") ?? 0;
    const resilience = findFact(snapshot, "verticals.resilience") ?? 0;
    const cost = findFact(snapshot, "verticals.cost") ?? 0;
    const unknown = findFact(snapshot, "verticals.unknown") ?? 0;
    return {
      text: `Verticals represented: change ${change}, resilience ${resilience}, cost ${cost}, unknown ${unknown}.`,
      citations: [
        { label: "change", value: String(change) },
        { label: "resilience", value: String(resilience) },
        { label: "cost", value: String(cost) },
        { label: "unknown", value: String(unknown) },
      ],
      followUps: ["list change tiles", "list cost tiles"],
    };
  }

  if (/failed|failure|error/.test(q)) {
    const failedTiles = tiles.filter((t) => t.failed === true);
    return {
      text:
        failedTiles.length === 0
          ? "No failed tiles right now."
          : `${failedTiles.length} tile(s) marked failed: ${failedTiles.map((t) => `${t.action_type ?? t.rule ?? "(no rule)"} on ${t.resource_type ?? "?"}`).slice(0, 6).join("; ")}`,
      citations: failedTiles.slice(0, 6).map((t) => ({
        label: String(t.action_type ?? t.rule ?? "(no rule)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: ["what verticals are they in?"],
    };
  }

  if (/stuck|stall/.test(q)) {
    const stuck = tiles.filter((t) => t.stuck === true);
    return {
      text: stuck.length === 0
        ? "No stuck tiles."
        : `${stuck.length} tile(s) stuck without reaching audit.`,
      citations: stuck.slice(0, 6).map((t) => ({
        label: String(t.action_type ?? "(routing)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }

  if (/tier|t0|t1|t2/.test(q)) {
    const t0 = findFact(snapshot, "tier.t0") ?? "0%";
    const t1 = findFact(snapshot, "tier.t1") ?? "0%";
    const t2 = findFact(snapshot, "tier.t2") ?? "0%";
    return {
      text: `Tier mix over the 60s window: T0 ${t0}, T1 ${t1}, T2 ${t2}.`,
      citations: [
        { label: "T0", value: String(t0) },
        { label: "T1", value: String(t1) },
        { label: "T2", value: String(t2) },
      ],
      followUps: ["what is the current EPS?"],
    };
  }

  if (/gate|auto|hil|deny/.test(q)) {
    const auto = findFact(snapshot, "gate.auto") ?? "0%";
    const hil = findFact(snapshot, "gate.hil") ?? "0%";
    const abstain = findFact(snapshot, "gate.abstain") ?? "0%";
    const deny = findFact(snapshot, "gate.deny") ?? "0%";
    return {
      text: `Gate mix (60s): auto ${auto}, hil ${hil}, abstain ${abstain}, deny ${deny}.`,
      citations: [
        { label: "auto", value: String(auto) },
        { label: "hil", value: String(hil) },
        { label: "abstain", value: String(abstain) },
        { label: "deny", value: String(deny) },
      ],
      followUps: [],
    };
  }

  if (/eps|per\s*sec|events?\s*per|throughput|rate/.test(q)) {
    return {
      text: `Throughput: ${findFact(snapshot, "eps") ?? "0.0"} events per second over the last 60s.`,
      citations: [{ label: "eps", value: String(findFact(snapshot, "eps") ?? "0.0") }],
      followUps: ["what is the session total?"],
    };
  }

  if (/session|total|since|watching/.test(q)) {
    return {
      text: `Watching this session for ${findFact(snapshot, "session.duration") ?? "-"}, ${findFact(snapshot, "session.total") ?? 0} terminal events observed.`,
      citations: [
        { label: "duration", value: String(findFact(snapshot, "session.duration") ?? "-") },
        { label: "total events", value: String(findFact(snapshot, "session.total") ?? 0) },
      ],
      followUps: [],
    };
  }

  if (/how many.*tile|tile.*count|total.*tile/.test(q)) {
    const active = findFact(snapshot, "tiles.active") ?? 0;
    const empty = findFact(snapshot, "tiles.empty") ?? 0;
    const shadow = findFact(snapshot, "tiles.shadow") ?? 0;
    return {
      text: `${active} active tile(s), ${empty} empty slot(s). ${shadow} tile(s) have executed in shadow mode.`,
      citations: [
        { label: "active", value: String(active) },
        { label: "empty", value: String(empty) },
        { label: "shadow", value: String(shadow) },
      ],
      followUps: [],
    };
  }

  if (/list.*tile|which tile|show.*tile/.test(q)) {
    const sample = tiles.slice(0, 8);
    return {
      text: sample.length === 0
        ? "No tiles to list right now."
        : `${sample.length} sample tile(s):\n` +
          sample
            .map(
              (t) =>
                `- ${t.action_type ?? t.rule ?? "(no rule)"} on ${t.resource_type ?? "?"} - tier ${t.tier ?? "abstain"}, gate ${t.gate_decision ?? "-"}`,
            )
            .join("\n"),
      citations: sample.map((t) => ({
        label: String(t.action_type ?? "(routing)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }

  return {
    text: `Live cockpit - ${snapshot.headline}. Ask about attention, tiles, verticals, gates, tiers, EPS, or session totals.`,
    citations: snapshot.facts.slice(0, 8).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function answerDashboard(q: string, snapshot: ViewSnapshot): Answer {
  if (/shadow/.test(q)) {
    return {
      text: `Shadow share: ${findFact(snapshot, "shadow_share")}. Enforce share: ${findFact(snapshot, "enforce_share")}.`,
      citations: [
        { label: "shadow", value: String(findFact(snapshot, "shadow_share")) },
        { label: "enforce", value: String(findFact(snapshot, "enforce_share")) },
      ],
      followUps: [],
    };
  }
  if (/hil|approval/.test(q)) {
    return {
      text: `${findFact(snapshot, "hil_pending")} approval(s) pending on the current audit window.`,
      citations: [{ label: "Approvals pending", value: String(findFact(snapshot, "hil_pending")) }],
      followUps: [],
    };
  }
  if (/(action|kind|outcome|common)/.test(q)) {
    const kinds = (snapshot.records?.by_action_kind ?? []) as readonly Record<string, unknown>[];
    const outcomes = (snapshot.records?.by_outcome ?? []) as readonly Record<string, unknown>[];
    return {
      text: `Top action kinds: ${kinds.slice(0, 5).map((r) => `${r.key} (${r.count})`).join(", ")}. Top outcomes: ${outcomes.slice(0, 5).map((r) => `${r.key} (${r.count})`).join(", ")}.`,
      citations: kinds.slice(0, 5).map((r) => ({ label: String(r.key), value: String(r.count) })),
      followUps: [],
    };
  }
  return {
    text: `Dashboard - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export function answerAudit(q: string, snapshot: ViewSnapshot): Answer {
  const rows = (snapshot.records?.items ?? []) as readonly Record<string, unknown>[];
  if (/how many|count/.test(q)) {
    return {
      text: `${rows.length} audit row(s) currently loaded in this view.`,
      citations: [{ label: "rows", value: String(rows.length) }],
      followUps: [],
    };
  }
  if (/mode|shadow|enforce/.test(q)) {
    const modes = new Map<string, number>();
    for (const r of rows) {
      const m = String(r.mode ?? "unknown");
      modes.set(m, (modes.get(m) ?? 0) + 1);
    }
    return {
      text: `Mode distribution: ${[...modes.entries()].map(([k, v]) => `${k}=${v}`).join(", ")}.`,
      citations: [...modes.entries()].map(([k, v]) => ({ label: k, value: String(v) })),
      followUps: [],
    };
  }
  if (/latest|newest|most recent|last/.test(q)) {
    const latest = rows[0];
    return {
      text: latest
        ? `Latest entry: seq ${latest.seq} at ${latest.recorded_at} - ${latest.action_kind} by ${latest.actor} in ${latest.mode} mode.`
        : "No audit rows loaded.",
      citations: latest
        ? [
            { label: "seq", value: String(latest.seq) },
            { label: "kind", value: String(latest.action_kind) },
            { label: "mode", value: String(latest.mode) },
          ]
        : [],
      followUps: [],
    };
  }
  return {
    text: `Audit - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Rules catalog
// ---------------------------------------------------------------------------

export function answerRules(q: string, snapshot: ViewSnapshot): Answer {
  const rules = (snapshot.records?.rules ?? []) as readonly Record<string, unknown>[];
  // Pull candidate search terms from the query (ascii tokens >= 3 chars) and
  // match them against the visible rule rows. This lets an offline operator
  // still get a grounded answer for rules currently on the page.
  const terms = q.match(/[a-z0-9-]{3,}/g) ?? [];
  const stop = new Set([
    "how", "the", "and", "for", "what", "which", "does", "recommended",
    "value", "values", "setting", "settings", "find", "show", "list", "rule", "rules",
  ]);
  const needles = terms.filter((w) => !stop.has(w));
  const hits = needles.length
    ? rules.filter((r) => {
        const hay = JSON.stringify(r).toLowerCase();
        return needles.some((w) => hay.includes(w));
      })
    : [];
  if (hits.length > 0) {
    const sample = hits.slice(0, 6);
    return {
      text:
        `${hits.length} matching rule(s) on this page:\n` +
        sample
          .map(
            (r) =>
              `- ${r.id} (${r.severity}, ${r.category} / ${r.resource_type}) - remediation ${r.remediation ?? "-"}`,
          )
          .join("\n"),
      citations: sample.map((r) => ({
        label: String(r.id),
        value: String(r.remediation ?? r.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }
  if (needles.length > 0) {
    return {
      text:
        `No rule matching "${needles.join(" ")}" is on the current page. ` +
        `Type it into the Rules search box to filter the full catalog ` +
        `(${findFact(snapshot, "total_rules") ?? "?"} rules, ` +
        `${findFact(snapshot, "active_rules") ?? "?"} active).`,
      citations: [
        { label: "total_rules", value: String(findFact(snapshot, "total_rules") ?? "?") },
        { label: "categories", value: String(findFact(snapshot, "categories_available") ?? "-") },
      ],
      followUps: [],
    };
  }
  return {
    text:
      `Rules catalog - ${snapshot.headline}. Categories available: ` +
      `${findFact(snapshot, "categories_available") ?? "-"}. ` +
      `Use the search box or the origin/category/severity/source filters to narrow it.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// HIL queue
// ---------------------------------------------------------------------------

export function answerHil(q: string, snapshot: ViewSnapshot): Answer {
  const items = (snapshot.records?.items ?? []) as readonly Record<string, unknown>[];
  if (/how many|count|waiting|pending/.test(q)) {
    return {
      text: `${items.length} item(s) waiting for approval.`,
      citations: [{ label: "pending", value: String(items.length) }],
      followUps: items.length > 0 ? ["list all pending kinds"] : [],
    };
  }
  if (/list|kinds?|show/.test(q)) {
    return {
      text: items.length === 0
        ? "The approval queue is empty."
        : `Waiting kinds: ${items.map((i) => i.action_kind).join(", ")}.`,
      citations: items.map((i) => ({ label: String(i.action_kind), value: String(i.reason ?? "") })),
      followUps: [],
    };
  }
  return {
    text: `Approvals - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Promotion gates
// ---------------------------------------------------------------------------

export function answerPromotion(q: string, snapshot: ViewSnapshot): Answer {
  const rows = (snapshot.records?.rows ?? []) as readonly Record<string, unknown>[];
  if (/ready/.test(q)) {
    const ready = rows.filter((r) => r.ready === true);
    return {
      text: ready.length === 0
        ? "No ActionTypes are ready to promote."
        : `Ready (${ready.length}): ${ready.map((r) => r.action_type_name).join(", ")}.`,
      citations: ready.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: `${(Number(r.accuracy) * 100).toFixed(1)}%`,
      })),
      followUps: ["which are blocked?"],
    };
  }
  if (/block/.test(q)) {
    const blocked = rows.filter((r) => r.ready !== true);
    return {
      text: `${blocked.length} ActionType(s) still blocked. Common gaps: ${blocked.slice(0, 5).flatMap((r) => (r.gaps as string[]) ?? []).slice(0, 6).join("; ")}.`,
      citations: blocked.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: String((r.gaps as string[])?.[0] ?? ""),
      })),
      followUps: ["which have policy escapes?"],
    };
  }
  if (/escape|violation/.test(q)) {
    const escapes = rows.filter((r) => Number(r.policy_escapes ?? 0) > 0);
    return {
      text: escapes.length === 0
        ? "No policy escapes recorded in the current window."
        : `${escapes.length} ActionType(s) with escapes: ${escapes.map((r) => `${r.action_type_name} (${r.policy_escapes})`).join(", ")}.`,
      citations: escapes.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: String(r.policy_escapes),
      })),
      followUps: [],
    };
  }
  return {
    text: `Promotion gates - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Blast radius
// ---------------------------------------------------------------------------

export function answerBlast(q: string, snapshot: ViewSnapshot): Answer {
  if (/(how many|count|affected)/.test(q)) {
    return {
      text: `${findFact(snapshot, "affected_count") ?? 0} resource(s) reachable at depth ${findFact(snapshot, "depth")}.`,
      citations: [
        { label: "affected", value: String(findFact(snapshot, "affected_count") ?? 0) },
        { label: "depth", value: String(findFact(snapshot, "depth")) },
      ],
      followUps: [],
    };
  }
  if (/(truncat|cap|limit)/.test(q)) {
    return {
      text: findFact(snapshot, "truncated") === true
        ? "Traversal WAS truncated at the depth cap; raise depth to see more."
        : "Traversal completed within the depth cap; no truncation.",
      citations: [{ label: "truncated", value: String(findFact(snapshot, "truncated")) }],
      followUps: [],
    };
  }
  return {
    text: `Blast radius - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Trace
// ---------------------------------------------------------------------------

export function answerTrace(q: string, snapshot: ViewSnapshot): Answer {
  if (/how many|step/.test(q)) {
    return {
      text: `${findFact(snapshot, "step_count") ?? 0} pipeline step(s) recorded for correlation ${findFact(snapshot, "correlation_id")}.`,
      citations: [
        { label: "steps", value: String(findFact(snapshot, "step_count") ?? 0) },
        { label: "correlation", value: String(findFact(snapshot, "correlation_id")) },
      ],
      followUps: [],
    };
  }
  if (/terminal|end|last/.test(q)) {
    return {
      text: `Terminal stage: ${findFact(snapshot, "terminal_stage") ?? "(none recorded)"}.`,
      citations: [{ label: "terminal", value: String(findFact(snapshot, "terminal_stage") ?? "-") }],
      followUps: [],
    };
  }
  return {
    text: `Trace - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

// ---------------------------------------------------------------------------
// Ontology
// ---------------------------------------------------------------------------

export function answerOntology(q: string, snapshot: ViewSnapshot): Answer {
  const objects = snapshot.records?.object_types ?? [];
  const relationships = snapshot.records?.relationships ?? [];
  const actions = snapshot.records?.action_types ?? [];
  const selected = String(findFact(snapshot, "selected_object_type") ?? "none");
  const listValues = (
    rows: readonly Record<string, unknown>[],
    ...keys: readonly string[]
  ): string[] => rows.slice(0, 40).map((row) => {
    for (const key of keys) {
      const value = row[key];
      if (typeof value === "string" && value) return value;
    }
    return "unknown";
  });
  const listCitations = (label: string, values: readonly string[]) =>
    values.slice(0, 8).map((value) => ({ label, value }));

  if (
    /(?:how|방법|어떻게|어디).*(?:query|browse|view|조회|탐색|봐)/.test(q) ||
    /(?:조회|탐색|봐).*(?:방법|어떻게|어디)/.test(q) ||
    /(?:query|browse|view|조회|탐색).*(?:ontology|온톨로지)/.test(q)
  ) {
    return {
      text:
        "Use the Objects, Links, and Actions tabs to inspect the ontology data. " +
        `Select an ObjectType such as ${selected} to browse its one-hop relationships and properties. ` +
        "The same read-only graph is available from GET /ontology/graph; this screen does not mutate it.",
      citations: snapshot.facts.slice(0, 4).map(factToCitation),
      followUps: [
        "list ontology object types",
        "list ontology relationships",
        "list ontology actions",
      ],
    };
  }
  if (/selected|선택/.test(q)) {
    return {
      text: `Selected ObjectType: ${selected}.`,
      citations: [{ label: "selected_object_type", value: selected }],
      followUps: [`what does ${selected} connect to?`],
    };
  }
  if (/connect|relationship|relation|관계|연결/.test(q)) {
    const related = relationships.filter((row) => row.from === selected || row.to === selected);
    const lines = related.map((row) => `${row.link}: ${row.from} -> ${row.to}`);
    return {
      text: lines.length > 0
        ? `${selected} relationships:\n${lines.map((line) => `- ${line}`).join("\n")}`
        : `No relationships for ${selected} are present in this snapshot.`,
      citations: listCitations("relationship", lines),
      followUps: [],
    };
  }
  if (/list|목록/.test(q) && /object|객체/.test(q)) {
    const values = listValues(objects, "name");
    return {
      text: `ObjectTypes:\n${values.map((value) => `- ${value}`).join("\n")}`,
      citations: listCitations("ObjectType", values),
      followUps: [],
    };
  }
  if (/list|목록/.test(q) && /link|relationship|링크|관계/.test(q)) {
    const values = listValues(relationships, "link", "name");
    return {
      text: `LinkTypes:\n${values.map((value) => `- ${value}`).join("\n")}`,
      citations: listCitations("LinkType", values),
      followUps: [],
    };
  }
  if (/list|목록/.test(q) && /action|액션|작업/.test(q)) {
    const values = listValues(actions, "name");
    return {
      text: `ActionTypes:\n${values.map((value) => `- ${value}`).join("\n")}`,
      citations: listCitations("ActionType", values),
      followUps: [],
    };
  }
  if (/object/.test(q)) {
    return {
      text: `${findFact(snapshot, "object_type_count") ?? 0} ObjectType(s) registered.`,
      citations: [{ label: "ObjectTypes", value: String(findFact(snapshot, "object_type_count") ?? 0) }],
      followUps: [],
    };
  }
  if (/link/.test(q)) {
    return {
      text: `${findFact(snapshot, "link_type_count") ?? 0} LinkType(s) registered.`,
      citations: [{ label: "LinkTypes", value: String(findFact(snapshot, "link_type_count") ?? 0) }],
      followUps: [],
    };
  }
  if (/action/.test(q)) {
    return {
      text: `${findFact(snapshot, "action_type_count") ?? 0} ActionType(s) registered.`,
      citations: [{ label: "ActionTypes", value: String(findFact(snapshot, "action_type_count") ?? 0) }],
      followUps: [],
    };
  }
  if (/screen.*for|purpose|용도/.test(q)) {
    return {
      text: snapshot.purpose ?? `Ontology - ${snapshot.headline}.`,
      citations: snapshot.facts.slice(0, 4).map(factToCitation),
      followUps: defaultFollowUps(snapshot),
    };
  }
  return {
    text: `Ontology - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}
