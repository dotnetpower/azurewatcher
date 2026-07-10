"""Format encoders that serialize a :class:`RenderedReport` for delivery.

Three upstream encoders:

- :class:`~fdai.core.reporting.formats.json_format.JsonFormatEncoder` -
  the FE contract; UTF-8, compact.
- :class:`~fdai.core.reporting.formats.markdown_format.MarkdownFormatEncoder` -
  notebook-style rendering suitable for a Postmortem PR.
- :class:`~fdai.core.reporting.formats.csv_format.CsvFormatEncoder` -
  spreadsheet export; flattens every table widget into one CSV.

Register your own by implementing
:class:`~fdai.core.reporting.contracts.FormatEncoder` and calling
:meth:`FormatRegistry.register` at the composition root.
"""

from __future__ import annotations

from fdai.core.reporting.formats.csv_format import CsvFormatEncoder
from fdai.core.reporting.formats.defaults import (
    default_format_encoders,
    install_default_formats,
)
from fdai.core.reporting.formats.json_format import JsonFormatEncoder
from fdai.core.reporting.formats.markdown_format import MarkdownFormatEncoder

__all__ = [
    "CsvFormatEncoder",
    "JsonFormatEncoder",
    "MarkdownFormatEncoder",
    "default_format_encoders",
    "install_default_formats",
]
