"""Base classes and semver / idempotency-key type aliases shared by every
domain-specific contract model.

Kept in a private submodule so the domain files (:mod:`.event`,
:mod:`.incident`, ...) all import from one place and the model-config /
strict-mode contract is defined exactly once.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Aliases mirroring the JSON Schema pattern for semver strings.
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", min_length=5)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=512)]


class _Base(BaseModel):
    """Base config shared by every contract model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


__all__ = ["IdempotencyKey", "SemVer", "_Base"]
