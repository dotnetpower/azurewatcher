"""Ontology types and event / action / rule schemas (versioned).

Ontology (Resource / Rule / Signal / Finding) plus event / action / rule
schemas. Public API. Re-exports the *interfaces* (Protocols, data models,
errors) that core modules depend on. Concrete implementations
(``PackageResourceSchemaRegistry``, ``JsonSchemaContractValidator``,
``JsonSchemaEventValidator``) are **intentionally not re-exported here** — they
must be imported from their submodules by the composition root only, so
``core/`` cannot accidentally depend on a concrete adapter (see
``docs/roadmap/project-structure.md § Customization via Dependency Injection``).
"""

from .models import (
    Action,
    ActionBlastRadius,
    ActionInterface,
    ActionPrecondition,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusComputation,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Decision,
    Event,
    IdempotencyKey,
    LinkCardinality,
    Mode,
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
    Operation,
    PreconditionKind,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    Provenance,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    SemVer,
    Severity,
    StopConditionKind,
    Tier,
)
from .registry import SchemaNotFoundError, SchemaRegistry
from .validation import (
    ContractValidationError,
    ContractValidator,
    EventValidator,
    ValidationIssue,
)

__all__ = [
    # data — enums
    "ActionInterface",
    "BlastRadiusComputation",
    "BlastRadiusScope",
    "Category",
    "CheckLogicKind",
    "Decision",
    "LinkCardinality",
    "Mode",
    "Operation",
    "PreconditionKind",
    "PropertyType",
    "RollbackKind",
    "RuleSource",
    "Severity",
    "StopConditionKind",
    "Tier",
    # data — aliases
    "IdempotencyKey",
    "SemVer",
    # data — models
    "Action",
    "ActionBlastRadius",
    "ActionPrecondition",
    "ActionStopCondition",
    "BlastRadius",
    "CheckLogic",
    "Event",
    "OntologyActionType",
    "OntologyLinkType",
    "OntologyObjectType",
    "PromotionGate",
    "PropertyDecl",
    "Provenance",
    "Remediation",
    "RollbackRef",
    "Rule",
    # DI seams (Protocols only — no concretes)
    "ContractValidator",
    "EventValidator",
    "SchemaRegistry",
    # error types
    "ContractValidationError",
    "SchemaNotFoundError",
    "ValidationIssue",
]
