"""ResourceTypeRegistry loader - canonical CSP-neutral resource_type vocabulary.

Mirrors the JSON Schema at ``resource_types.schema.json`` and adds
duplicate-id detection (the schema has no ``uniqueItemProperties``
keyword in Draft 2020-12). Follows the same aggregate-issue pattern as
:mod:`aiopspilot.rule_catalog.schema.exemption` so a reviewer sees every
problem in one shot.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

_SCHEMA_PACKAGE = "aiopspilot.rule_catalog.schema"
_SCHEMA_FILE = "resource_types.schema.json"


class ResourceTypeCategory(StrEnum):
    COMPUTE = "compute"
    NETWORK = "network"
    STORAGE = "storage"
    DATABASE = "database"
    SECURITY = "security"
    OBSERVABILITY = "observability"
    GOVERNANCE = "governance"


class ResourceTypeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9\-]*(\.[a-z][a-z0-9\-]*)*$")]
    category: ResourceTypeCategory
    description: Annotated[str, Field(min_length=1, max_length=512)]
    azure_arm_type: str | None = None
    typical_parents: list[str] = Field(default_factory=list)


class ResourceTypeRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    types: tuple[ResourceTypeEntry, ...]

    def ids(self) -> set[str]:
        return {t.id for t in self.types}

    def get(self, type_id: str) -> ResourceTypeEntry:
        for entry in self.types:
            if entry.id == type_id:
                return entry
        raise KeyError(type_id)

    def __iter__(self) -> Iterator[ResourceTypeEntry]:  # type: ignore[override]
        return iter(self.types)


@dataclass(frozen=True, slots=True)
class ResourceTypeIssue:
    key: str
    message: str


class ResourceTypeRegistryError(ValueError):
    def __init__(self, issues: list[ResourceTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"resource-type registry validation failed: {preview}{suffix}")


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def _duplicate_ids(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    dupes: list[str] = []
    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        seen[entry_id] = seen.get(entry_id, 0) + 1
        if seen[entry_id] == 2:
            dupes.append(entry_id)
    return dupes


def load_resource_type_registry_from_mapping(
    raw: Mapping[str, Any],
) -> ResourceTypeRegistry:
    """Validate ``raw`` against the JSON Schema + duplicate-id rule and return the model."""
    issues: list[ResourceTypeIssue] = []

    schema = _load_json_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ResourceTypeIssue(key=path, message=err.message))

    types_field = raw.get("types") if isinstance(raw, Mapping) else None
    if isinstance(types_field, list):
        for dup in _duplicate_ids(t for t in types_field if isinstance(t, Mapping)):
            issues.append(
                ResourceTypeIssue(
                    key=f"types[id={dup}]",
                    message="duplicate resource_type id",
                )
            )

    if issues:
        raise ResourceTypeRegistryError(issues)

    try:
        return ResourceTypeRegistry.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ResourceTypeIssue(key=loc or "<root>", message=e["msg"]))
        else:
            issues.append(ResourceTypeIssue(key="<root>", message=str(exc)))
        raise ResourceTypeRegistryError(issues) from exc


__all__ = [
    "ResourceTypeCategory",
    "ResourceTypeEntry",
    "ResourceTypeIssue",
    "ResourceTypeRegistry",
    "ResourceTypeRegistryError",
    "load_resource_type_registry_from_mapping",
]
