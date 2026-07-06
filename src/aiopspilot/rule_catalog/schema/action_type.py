"""ActionType catalog loader - reads YAML instances from
``rule-catalog/action-types/`` and validates against the ontology
``action-type`` JSON Schema plus the :class:`OntologyActionType` pydantic
model. Aggregates every issue in a single :class:`ActionTypeCatalogError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from aiopspilot.shared.contracts.models import Mode, OntologyActionType
from aiopspilot.shared.contracts.registry import SchemaRegistry

_ACTION_TYPE_SCHEMA_NAME = "ontology/action-type"


@dataclass(frozen=True, slots=True)
class ActionTypeIssue:
    key: str
    message: str


class ActionTypeCatalogError(ValueError):
    """Aggregate error surfaced when loading an ActionType YAML fails."""

    def __init__(self, issues: list[ActionTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"action-type catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_action_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    origin: str = "<mapping>",
) -> OntologyActionType:
    """Validate a single ActionType mapping and return the pydantic model.

    - Aggregates JSON Schema violations and pydantic issues under one
      :class:`ActionTypeCatalogError`.
    - Enforces the P1 upstream invariant: ``default_mode == "shadow"``
      (a fork may loosen this only via a governance PR that also updates
      the promotion gate).
    """
    issues: list[ActionTypeIssue] = []

    schema = schema_registry.get(_ACTION_TYPE_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ActionTypeIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise ActionTypeCatalogError(issues)

    try:
        model = OntologyActionType.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ActionTypeIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(ActionTypeIssue(key=f"{origin}:<root>", message=str(exc)))
        raise ActionTypeCatalogError(issues) from exc

    if model.default_mode is not Mode.SHADOW:
        raise ActionTypeCatalogError(
            [
                ActionTypeIssue(
                    key=f"{origin}:default_mode",
                    message=(
                        "upstream ActionType MUST default to shadow "
                        "(coding-conventions.instructions.md § shadow-first)"
                    ),
                )
            ]
        )

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.glob("*.yaml")):
        if path.name == "README.md":
            continue
        yield path


def load_action_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
) -> tuple[OntologyActionType, ...]:
    """Load every ActionType YAML under ``root`` (non-recursive).

    Fails closed: any issue in any file raises a single
    :class:`ActionTypeCatalogError` carrying every issue across every file.
    Duplicate ``name`` across files is a hard error.
    """
    aggregated: list[ActionTypeIssue] = []
    loaded: list[OntologyActionType] = []
    seen_names: dict[str, str] = {}

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(ActionTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            aggregated.append(ActionTypeIssue(key=path.name, message="top-level must be a mapping"))
            continue
        try:
            model = load_action_type_from_mapping(
                raw, schema_registry=schema_registry, origin=path.name
            )
        except ActionTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(model.name)
        if prior is not None:
            aggregated.append(
                ActionTypeIssue(
                    key=path.name,
                    message=f"duplicate ActionType name {model.name!r} (also in {prior})",
                )
            )
            continue
        seen_names[model.name] = path.name
        loaded.append(model)

    if aggregated:
        raise ActionTypeCatalogError(aggregated)

    return tuple(loaded)


def action_type_names(catalog: Iterable[OntologyActionType]) -> set[str]:
    return {a.name for a in catalog}


__all__ = [
    "ActionTypeCatalogError",
    "ActionTypeIssue",
    "action_type_names",
    "load_action_type_catalog",
    "load_action_type_from_mapping",
]
