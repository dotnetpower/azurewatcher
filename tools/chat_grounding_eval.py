#!/usr/bin/env python3
"""Live grounded-accuracy harness for the console chat backend.

Fires a fixed set of (snapshot, prompt) cases at a running read-api ``/chat``
endpoint and scores each reply on two axes the deck actually cares about:

- **Grounding hit**: for a data question, every expected snapshot value the
  answer must cite is present verbatim.
- **Hallucination guard**: for a question whose value is NOT in the snapshot,
  the reply must refuse / redirect (never fabricate a concrete value).

This is a *live* harness (it calls a real model), so it lives under ``tools/``
and is NOT part of the deterministic CI suite. Run it against a local backend:

    uv run python tools/chat_grounding_eval.py --base-url http://127.0.0.1:8010

Non-English prompt strings are the literal subject under test (the operator's
own-language phrasing) and are written as ``\\uXXXX`` escapes so this source
stays ASCII, matching the language-policy "quoted data" exception.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Refusal markers (EN + KO, KO escaped) an answer uses when the value is absent.
_REFUSAL_MARKERS: tuple[str, ...] = (
    "does not",
    "not include",
    "no information",
    "not contain",
    "unable",
    "search/filter",
    "search box",
    "\uc5c6\uc2b5\ub2c8\ub2e4",  # "does not exist / none"
    "\uc5c6\uc5b4",  # "none" (casual)
    "\ucc3e\uc744 \uc218",  # "you can find ... (via search)"
    "\uac80\uc0c9",  # "search"
)


@dataclass(frozen=True)
class Case:
    name: str
    prompt: str
    view_context: dict[str, Any]
    expect_substrings: tuple[str, ...] = ()
    expect_refusal: bool = False
    history: list[dict[str, str]] = field(default_factory=list)


_LIVE = {
    "routeId": "live",
    "routeLabel": "Live cockpit",
    "headline": "60 tiles - 4.2 eps - 3 failed",
    "facts": [
        {"key": "eps", "value": "4.2"},
        {"key": "attention.total", "value": 3},
        {"key": "tier.t0", "value": "78%"},
        {"key": "tier.t1", "value": "17%"},
        {"key": "tier.t2", "value": "5%"},
    ],
}
_AUDIT = {
    "routeId": "audit",
    "headline": "2 rows loaded",
    "facts": [{"key": "loaded_rows", "value": 2}],
    "records": {
        "items": [
            {
                "seq": 42,
                "recorded_at": "2026-07-09T05:00:00Z",
                "actor": "thor",
                "action_kind": "remediate.tag-add",
                "mode": "enforce",
                "event_id": "e-1",
            },
        ]
    },
}
_ONTOLOGY = {
    "routeId": "ontology",
    "headline": "13 ObjectTypes - 19 LinkTypes",
    "facts": [
        {"key": "object_type_count", "value": 13},
        {"key": "link_type_count", "value": 19},
    ],
}

CASES: list[Case] = [
    # --- grounding (data questions must cite the snapshot value) ---
    Case("eps_en", "what is the current EPS?", _LIVE, expect_substrings=("4.2",)),
    Case(
        "attention_ko",
        "\uba87 \uac1c\uac00 \uc8fc\uc758\uac00 \ud544\uc694\ud574?",
        _LIVE,
        expect_substrings=("3",),
    ),
    Case("t0_share", "what is the T0 share?", _LIVE, expect_substrings=("78%",)),
    Case(
        "audit_latest", "what is the latest audit entry?", _AUDIT, expect_substrings=("42", "thor")
    ),
    Case(
        "audit_mode_ko",
        "\ucd5c\uadfc \ud56d\ubaa9\uc740 \uc5b4\ub5a4 \ubaa8\ub4dc\uc57c?",
        _AUDIT,
        expect_substrings=("enforce",),
    ),
    Case(
        "ont_objects", "how many ObjectTypes are registered?", _ONTOLOGY, expect_substrings=("13",)
    ),
    Case(
        "ont_links_ja",
        "\u30ea\u30f3\u30af\u30bf\u30a4\u30d7\u306f\u3044\u304f\u3064\uff1f",
        _ONTOLOGY,
        expect_substrings=("19",),
    ),  # JA: "how many link types?"
    # --- hallucination guard (value absent -> must refuse/redirect) ---
    Case("cpu_absent", "what is the database CPU usage?", _LIVE, expect_refusal=True),
    Case(
        "cost_absent_ko",
        "\uc774 \ub9ac\uc18c\uc2a4 \uc6d4 \ube44\uc6a9\uc774 \uc5bc\ub9c8\uc57c?",
        _AUDIT,
        expect_refusal=True,
    ),  # KO: "monthly cost?"
    Case(
        "region_absent", "which Azure region is this deployed in?", _ONTOLOGY, expect_refusal=True
    ),
    # --- multi-turn (follow-up must stay grounded in the same snapshot) ---
    Case(
        "followup_en",
        "and how many are failed?",
        _LIVE,
        expect_substrings=("3",),
        history=[
            {"role": "user", "content": "how many tiles are there?"},
            {"role": "assistant", "content": "There are 60 tiles, 3 failed."},
        ],
    ),
]


def _ask(base_url: str, case: Case) -> str:
    payload = json.dumps(
        {"prompt": case.prompt, "view_context": case.view_context, "history": case.history}
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - local dev harness, http/https only
        base_url.rstrip("/") + "/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        return str(body.get("answer", ""))
    except urllib.error.HTTPError as exc:
        return f"<HTTP {exc.code}>"
    except Exception as exc:  # noqa: BLE001 - report and continue
        return f"<ERROR {exc}>"


def _score(case: Case, answer: str) -> tuple[bool, str]:
    low = answer.lower()
    if case.expect_refusal:
        refused = any(m.lower() in low for m in _REFUSAL_MARKERS)
        return refused, "refused" if refused else "HALLUCINATED (gave a value)"
    missing = [s for s in case.expect_substrings if s.lower() not in low]
    if missing:
        return False, f"missing {missing}"
    return True, "grounded"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8010")
    args = ap.parse_args()

    passed = 0
    hallucinations = 0
    print(f"chat grounded-accuracy harness -> {args.base_url}\n")
    for case in CASES:
        answer = _ask(args.base_url, case)
        ok, why = _score(case, answer)
        if ok:
            passed += 1
        elif case.expect_refusal:
            hallucinations += 1
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case.name:16} {why:28} | {answer[:90].strip()}")

    total = len(CASES)
    print(
        f"\naccuracy: {passed}/{total} ({100 * passed // total}%)  hallucinations: {hallucinations}"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
