"""Catalog-driven chaos-scenario runner.

Unlike `scripts/run-enforce-scenarios.py` (which hardcodes the 10
upstream reference scenarios) and `scripts/measure-detection-latency.py`
(same, but with a probing runner), this driver loads scenarios from
`rule-catalog/chaos-scenarios/` and dispatches each through the
:class:`~fdai.core.chaos.factory.ScenarioFactory`. It is the runtime
answer to "the catalog says X; does the delivery layer know how to
execute X?".

Usage:

    # Dry-run: report which entries this composition can execute
    python scripts/run-catalog-scenario.py --list

    # Dispatch-check (no substrate): build every executable
    # (injector, probe) pair and print PASS / FAIL per entry
    python scripts/run-catalog-scenario.py --dry-run

    # Enforce one scenario end-to-end against the FDAI_ENFORCE_* substrate
    python scripts/run-catalog-scenario.py --run chaos.chaos-mesh.pod-failure

    # Enforce every executable entry (safe: needs-injector entries
    # are filtered out before injection)
    python scripts/run-catalog-scenario.py --run-all

Substrate config comes from the same `FDAI_ENFORCE_*` env vars the
other enforce runners read; see `scripts/run-enforce-scenarios.py` for
the full list. Missing env vars in `--run` / `--run-all` mode fail
fast; `--list` and `--dry-run` need no env vars.

Reports land under `logs/catalog-runs/<timestamp>/`. Every run writes
one JSON per scenario plus a `report.json` + `summary.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.chaos.contract import ExperimentResult
from fdai.core.chaos.factory import ScenarioFactory, UnavailableInjectorError
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.scenario_catalog import CatalogEntry, load_all
from fdai.delivery.chaos.factories import default_factory
from fdai.shared.contracts.models import Mode


def _env_or_none(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v else None


def _substrate_context() -> dict[str, Any]:
    """Read FDAI_ENFORCE_* env vars; fail fast when any is missing."""
    required = {
        "FDAI_ENFORCE_SUB_ID": "sub_id",
        "FDAI_ENFORCE_RG": "resource_group",
        "FDAI_ENFORCE_AKS_CONTEXT": "kubectl_context",
        "FDAI_ENFORCE_NS": "workload_namespace",
        "FDAI_ENFORCE_CHAOS_NS": "chaos_namespace",
        "FDAI_ENFORCE_BACKEND_DEPLOY": "backend_deployment",
        "FDAI_ENFORCE_BACKEND_SVC": "backend_service",
        "FDAI_ENFORCE_BACKEND_LABEL": "workload_label_raw",
        "FDAI_ENFORCE_VM": "vm_name",
    }
    missing = [env for env in required if not os.environ.get(env)]
    if missing:
        raise SystemExit(f"missing required env vars for --run / --run-all: {', '.join(missing)}")
    ctx: dict[str, Any] = {name: os.environ[env] for env, name in required.items()}
    # Normalize the workload_label: BACKEND_LABEL is `app=api-backend`,
    # but the CRD body just needs the value on the right of `=`.
    raw = ctx.pop("workload_label_raw")
    ctx["workload_label"] = raw.split("=", 1)[-1] if "=" in raw else raw
    ctx["vm_resource_id"] = (
        f"/subscriptions/{ctx['sub_id']}/resourceGroups/{ctx['resource_group']}"
        f"/providers/Microsoft.Compute/virtualMachines/{ctx['vm_name']}"
    )
    ctx["backend_container"] = os.environ.get("FDAI_ENFORCE_BACKEND_CONTAINER", "web")
    ctx["backend_restore_replicas"] = int(os.environ.get("FDAI_ENFORCE_BACKEND_REPLICAS", "3"))
    ctx["backend_image"] = os.environ.get("FDAI_ENFORCE_BACKEND_IMAGE", "nginx")
    return ctx


def _serialize(result: ExperimentResult) -> dict[str, Any]:
    d = dataclasses.asdict(result)
    d["mode"] = result.mode.value
    d["outcome"] = result.outcome.value
    d["started_at"] = result.started_at.isoformat()
    d["ended_at"] = result.ended_at.isoformat()
    d["targets"] = list(result.targets)
    d["reverted"] = result.reverted
    return d


async def _run_one(
    entry: CatalogEntry,
    factory: ScenarioFactory,
    ctx: dict[str, Any],
    out_dir: Path,
    max_hold_seconds: float,
) -> dict[str, Any]:
    """Build injector + probe, run the harness once, persist JSON."""
    payload: dict[str, Any]
    t0 = time.monotonic()
    try:
        injector, probe = factory.build(entry, ctx)
    except (UnavailableInjectorError, Exception) as exc:  # noqa: BLE001 - reported as JSON
        payload = {
            "scenario_id": entry.id,
            "outcome": "build_error",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
        (out_dir / f"{_slugify(entry.id)}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        print(f"[build_error] {entry.id}: {exc}", flush=True)
        return payload

    scenario = _to_fault_scenario(entry)
    approved_targets = [
        os.environ.get("FDAI_ENFORCE_BACKEND_LABEL", ctx.get("workload_label", "api-backend"))
    ]
    harness = FaultInjectionHarness(
        injectors=[injector],
        probe=probe,
        operation_timeout_seconds=180.0,
        rollback_timeout_seconds=180.0,
        max_hold_seconds=max_hold_seconds,
    )
    try:
        result = await harness.run(scenario, approved_targets=approved_targets, mode=Mode.ENFORCE)
        payload = _serialize(result)
        payload["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    except Exception as exc:  # noqa: BLE001 - report driver errors
        payload = {
            "scenario_id": entry.id,
            "outcome": "driver_error",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
    (out_dir / f"{_slugify(entry.id)}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[{payload.get('outcome', '?')}] {entry.id} "
        f"detected={payload.get('detected')} "
        f"reverted={payload.get('reverted')} "
        f"elapsed={payload.get('elapsed_seconds')}s",
        flush=True,
    )
    return payload


def _slugify(scenario_id: str) -> str:
    return scenario_id.replace(".", "-").replace("/", "-")


def _to_fault_scenario(entry: CatalogEntry):
    """Adapt a CatalogEntry to the harness's FaultScenario dataclass."""
    from fdai.core.chaos.contract import FaultScenario

    return FaultScenario(
        scenario_id=entry.id,
        fault_type=str(entry.spec.get("fault_family", "unknown")),
        description=str(entry.spec.get("description", entry.id)),
        target_selector=f"catalog:{entry.id}",
        expected_signal=str(entry.expected_signal),
        blast_radius_cap=int(entry.spec.get("blast_radius_cap", 1)),
        duration_seconds=float(entry.spec.get("duration_seconds", 360.0)),
        params={str(k): str(v) for k, v in (entry.spec.get("params") or {}).items()},
        rollback_note=str(entry.spec.get("rollback_note", "")),
    )


def _list_command(factory: ScenarioFactory) -> int:
    entries = load_all()
    executable = factory.executable_entries(entries)
    non_exec = [e for e in entries if e not in executable]
    print(f"catalog: {len(entries)} entries")
    print(f"executable via default factory: {len(executable)}")
    print(f"non-executable (needs-injector or missing probe): {len(non_exec)}")
    if len(executable):
        print("\nexecutable ids:")
        for e in executable:
            print(f"  - {e.id}  injector={e.spec['injector']}  signal={e.expected_signal}")
    return 0


async def _dry_run(factory: ScenarioFactory) -> int:
    """Build every executable pair with a synthetic context; report per-entry PASS/FAIL."""
    ctx = {
        "sub_id": "00000000-0000-0000-0000-000000000000",
        "kubectl_context": "dry-ctx",
        "workload_namespace": "demo",
        "workload_label": "api-backend",
        "chaos_namespace": "chaos-mesh",
        "backend_deployment": "api-backend",
        "backend_service": "api-backend",
        "backend_container": "web",
        "backend_restore_replicas": 3,
        "backend_image": "nginx",
        "resource_group": "rg-test",
        "vm_name": "vm-test",
        "vm_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-test"
        ),
    }
    entries = factory.executable_entries(load_all())
    fails = 0
    for e in entries:
        try:
            factory.build(e, ctx)
        except Exception as exc:  # noqa: BLE001 - dry-run: never raise
            fails += 1
            print(f"FAIL {e.id}: {type(exc).__name__}:{exc}", flush=True)
    print(f"\ndry-run: {len(entries) - fails}/{len(entries)} entries dispatchable", flush=True)
    return 1 if fails else 0


async def _run_one_by_id(scenario_id: str, factory: ScenarioFactory) -> int:
    ctx = _substrate_context()
    entries = [e for e in load_all() if e.id == scenario_id]
    if not entries:
        raise SystemExit(f"scenario id {scenario_id!r} not found in catalog")
    entry = entries[0]
    if not factory.is_executable(entry):
        raise SystemExit(
            f"{scenario_id!r} is not executable via the default factory "
            f"(injector={entry.spec['injector']!r}, signal={entry.expected_signal!r})"
        )
    out_dir = _report_dir()
    max_hold = float(os.environ.get("FDAI_MAX_HOLD_SECONDS", "180"))
    payload = await _run_one(entry, factory, ctx, out_dir, max_hold)
    (out_dir / "report.json").write_text(json.dumps({"runs": [payload]}, indent=2, sort_keys=True))
    _write_summary(out_dir, [payload])
    return 0 if payload.get("outcome") == "validated" else 1


async def _run_all(factory: ScenarioFactory, limit: int | None) -> int:
    ctx = _substrate_context()
    entries = factory.executable_entries(load_all())
    if limit is not None:
        entries = entries[:limit]
    out_dir = _report_dir()
    max_hold = float(os.environ.get("FDAI_MAX_HOLD_SECONDS", "180"))
    reports: list[dict[str, Any]] = []
    for e in entries:
        reports.append(await _run_one(e, factory, ctx, out_dir, max_hold))
        await asyncio.sleep(10)
    (out_dir / "report.json").write_text(json.dumps({"runs": reports}, indent=2, sort_keys=True))
    _write_summary(out_dir, reports)
    validated = sum(1 for r in reports if r.get("outcome") == "validated")
    print(f"\nsummary: {validated}/{len(reports)} validated  ->  {out_dir}", flush=True)
    return 0 if validated == len(reports) else 1


def _report_dir() -> Path:
    root = Path("logs/catalog-runs") / datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_summary(out_dir: Path, reports: list[dict[str, Any]]) -> None:
    lines = [
        "# Catalog run summary",
        "",
        f"Report root: `{out_dir}`",
        "",
        "| Scenario | Outcome | Detected | Reverted | Elapsed (s) | Error |",
        "|----------|---------|----------|----------|-------------|-------|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.get('scenario_id')}` | {r.get('outcome')} | "
            f"{r.get('detected')} | {r.get('reverted')} | "
            f"{r.get('elapsed_seconds')} | {r.get('error') or ''} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--list",
        action="store_true",
        help="Report executable coverage; no substrate needed.",
    )
    grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Build every executable pair with a synthetic context; no substrate needed.",
    )
    grp.add_argument("--run", metavar="SCENARIO_ID", help="Enforce one scenario end-to-end.")
    grp.add_argument(
        "--run-all",
        action="store_true",
        help="Enforce every executable scenario end-to-end.",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="Cap on --run-all (executes the first N executable entries).",
    )
    args = p.parse_args(argv)

    factory = default_factory()

    if args.list:
        return _list_command(factory)
    if args.dry_run:
        return asyncio.run(_dry_run(factory))
    if args.run:
        return asyncio.run(_run_one_by_id(args.run, factory))
    if args.run_all:
        return asyncio.run(_run_all(factory, args.limit))
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
