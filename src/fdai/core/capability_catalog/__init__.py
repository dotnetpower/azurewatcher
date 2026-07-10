"""Capability catalog (SRE-agent slide 20).

A customer-agnostic registry of control-plane capabilities the read-only
console renders so operators can discover what FDAI can do, each entry's
safety class, and its default autonomy mode. Listing a capability grants no
execution eligibility - the entries are inert metadata.
"""

from __future__ import annotations

from fdai.core.capability_catalog.catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    DuplicateCapabilityError,
    SideEffectClass,
)
from fdai.core.capability_catalog.defaults import default_capability_catalog

__all__ = [
    "Capability",
    "CapabilityCatalog",
    "CapabilityCategory",
    "DuplicateCapabilityError",
    "SideEffectClass",
    "default_capability_catalog",
]
