"""Trust-verified Markdown skill catalog for runtime prompt projection."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Protocol

import yaml

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MAX_SKILL_BYTES = 64 * 1024
_MANIFEST_KEYS = frozenset(
    {
        "name",
        "version",
        "description",
        "source",
        "body_sha256",
        "required_tools",
        "allowed_agents",
    }
)


@dataclass(frozen=True, slots=True)
class SkillManifest:
    name: str
    version: str
    description: str
    source: str
    body_sha256: str
    required_tools: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("skill name MUST be lowercase ASCII with dot or hyphen separators")
        if _VERSION_PATTERN.fullmatch(self.version) is None:
            raise ValueError("skill version MUST use MAJOR.MINOR.PATCH")
        if not self.description.strip() or not self.source.strip():
            raise ValueError("skill description and source MUST be non-empty")
        if _SHA256_PATTERN.fullmatch(self.body_sha256) is None:
            raise ValueError("skill body_sha256 MUST be a lowercase SHA-256 digest")
        if len(set(self.required_tools)) != len(self.required_tools):
            raise ValueError("skill required_tools MUST NOT contain duplicates")
        if len(set(self.allowed_agents)) != len(self.allowed_agents):
            raise ValueError("skill allowed_agents MUST NOT contain duplicates")


@dataclass(frozen=True, slots=True)
class RuntimeSkill:
    manifest: SkillManifest
    body: str
    enabled: bool = False


class SkillTrustVerifier(Protocol):
    """Verify detached publisher provenance for one skill artifact."""

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool: ...


class SkillCatalogError(ValueError):
    """Skill installation or activation failed before prompt projection."""


class SkillCatalog:
    """Immutable catalog; reviewed skills install disabled and enable explicitly."""

    __slots__ = ("_skills",)

    def __init__(self, skills: Mapping[str, RuntimeSkill] | None = None) -> None:
        self._skills = MappingProxyType(dict(skills or {}))

    def install(self, raw_markdown: bytes, *, verifier: SkillTrustVerifier) -> SkillCatalog:
        skill = parse_skill_markdown(raw_markdown)
        if skill.manifest.name in self._skills:
            raise SkillCatalogError(f"skill {skill.manifest.name!r} is already installed")
        if not verifier.verify(skill, raw_markdown):
            raise SkillCatalogError("skill publisher trust verification failed")
        skills = dict(self._skills)
        skills[skill.manifest.name] = skill
        return SkillCatalog(skills)

    def enable(
        self,
        name: str,
        *,
        available_tools: frozenset[str],
        known_agents: frozenset[str],
    ) -> SkillCatalog:
        current = self.get(name)
        missing_tools = set(current.manifest.required_tools) - available_tools
        if missing_tools:
            raise SkillCatalogError(f"skill requires unavailable tools: {sorted(missing_tools)}")
        unknown_agents = set(current.manifest.allowed_agents) - known_agents
        if unknown_agents:
            raise SkillCatalogError(f"skill references unknown agents: {sorted(unknown_agents)}")
        skills = dict(self._skills)
        skills[name] = replace(current, enabled=True)
        return SkillCatalog(skills)

    def disable(self, name: str) -> SkillCatalog:
        current = self.get(name)
        skills = dict(self._skills)
        skills[name] = replace(current, enabled=False)
        return SkillCatalog(skills)

    def uninstall(self, name: str) -> SkillCatalog:
        current = self.get(name)
        if current.enabled:
            raise SkillCatalogError("disable a skill before uninstalling it")
        skills = dict(self._skills)
        del skills[name]
        return SkillCatalog(skills)

    def get(self, name: str) -> RuntimeSkill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise SkillCatalogError(f"skill {name!r} is not installed") from exc

    def list(self) -> tuple[RuntimeSkill, ...]:
        return tuple(self._skills[name] for name in sorted(self._skills))

    def prompt_for(
        self,
        *,
        agent: str,
        available_tools: frozenset[str],
        max_chars: int,
    ) -> str:
        """Project complete eligible skill blocks or fail before truncating one."""
        if max_chars < 1:
            raise ValueError("skill prompt budget MUST be positive")
        blocks: list[str] = []
        for skill in self.list():
            manifest = skill.manifest
            if not skill.enabled:
                continue
            if manifest.allowed_agents and agent not in manifest.allowed_agents:
                continue
            missing = set(manifest.required_tools) - available_tools
            if missing:
                raise SkillCatalogError(
                    f"enabled skill {manifest.name!r} lost required tools: {sorted(missing)}"
                )
            blocks.append(
                f'<skill name="{manifest.name}" version="{manifest.version}" trusted="true">\n'
                f"{skill.body}</skill>"
            )
        prompt = "\n".join(blocks)
        if len(prompt) > max_chars:
            raise SkillCatalogError("eligible skill prompt exceeds the configured budget")
        return prompt


def parse_skill_markdown(raw_markdown: bytes) -> RuntimeSkill:
    """Parse strict YAML front matter and verify the normalized body digest."""
    if len(raw_markdown) > _MAX_SKILL_BYTES:
        raise SkillCatalogError("skill artifact exceeds the 64 KiB limit")
    try:
        text = raw_markdown.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillCatalogError("skill artifact MUST be UTF-8") from exc
    if not text.startswith("---\n"):
        raise SkillCatalogError("skill artifact requires YAML front matter")
    try:
        front_matter, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise SkillCatalogError("skill front matter is not terminated") from exc
    try:
        values = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise SkillCatalogError("skill front matter is invalid YAML") from exc
    if not isinstance(values, Mapping):
        raise SkillCatalogError("skill front matter MUST be a mapping")
    unknown = set(values) - _MANIFEST_KEYS
    if unknown:
        raise SkillCatalogError(f"skill front matter has unknown keys: {sorted(unknown)}")
    normalized_body = _normalize_body(body)
    try:
        manifest = SkillManifest(
            name=_required_string(values, "name"),
            version=_required_string(values, "version"),
            description=_required_string(values, "description"),
            source=_required_string(values, "source"),
            body_sha256=_required_string(values, "body_sha256"),
            required_tools=_string_tuple(values, "required_tools"),
            allowed_agents=_string_tuple(values, "allowed_agents"),
        )
    except ValueError as exc:
        raise SkillCatalogError(str(exc)) from exc
    if skill_body_digest(normalized_body) != manifest.body_sha256:
        raise SkillCatalogError("skill body digest does not match front matter")
    return RuntimeSkill(manifest=manifest, body=normalized_body)


def skill_body_digest(body: str) -> str:
    return hashlib.sha256(_normalize_body(body).encode()).hexdigest()


def _normalize_body(body: str) -> str:
    normalized = body.strip()
    if not normalized:
        raise SkillCatalogError("skill body MUST be non-empty")
    return normalized + "\n"


def _required_string(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"skill {key} MUST be a non-empty string")
    return value.strip()


def _string_tuple(values: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = values.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"skill {key} MUST be an array of non-empty strings")
    return tuple(value)


__all__ = [
    "RuntimeSkill",
    "SkillCatalog",
    "SkillCatalogError",
    "SkillManifest",
    "SkillTrustVerifier",
    "parse_skill_markdown",
    "skill_body_digest",
]
