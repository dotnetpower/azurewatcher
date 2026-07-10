"""Ship-with-upstream default format encoders.

:func:`install_default_formats` registers ``json`` (default), ``markdown``,
and ``csv`` on a :class:`~fdai.core.reporting.registry.FormatRegistry`.
A fork adds its own encoder by implementing
:class:`~fdai.core.reporting.contracts.FormatEncoder` and calling
:meth:`FormatRegistry.register`.
"""

from __future__ import annotations

from collections.abc import Iterable

from fdai.core.reporting.contracts import FormatEncoder
from fdai.core.reporting.formats.csv_format import CsvFormatEncoder
from fdai.core.reporting.formats.json_format import JsonFormatEncoder
from fdai.core.reporting.formats.markdown_format import MarkdownFormatEncoder
from fdai.core.reporting.registry import FormatRegistry


def default_format_encoders() -> Iterable[FormatEncoder]:
    return (JsonFormatEncoder(), MarkdownFormatEncoder(), CsvFormatEncoder())


def install_default_formats(registry: FormatRegistry) -> FormatRegistry:
    """Register every default encoder on ``registry`` and return it."""
    for encoder in default_format_encoders():
        registry.register(encoder)
    return registry


__all__ = ["default_format_encoders", "install_default_formats"]
