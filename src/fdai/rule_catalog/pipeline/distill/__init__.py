"""Manual distillation pipeline stage.

Deterministic verification helpers for the compile-side of the rule catalog
(see ``docs/roadmap/rules-and-detection/manual-distillation.md``). The
:class:`~fdai.shared.providers.distiller.Distiller` seam (LLM-backed, fork-owned)
produces candidates; this package supplies the deterministic checks that run over
them - starting with the false-negative coverage diff.
"""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.coverage import analyze_coverage

__all__ = ["analyze_coverage"]
