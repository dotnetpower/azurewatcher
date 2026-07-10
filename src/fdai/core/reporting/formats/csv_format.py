"""CSV format encoder - flattens every table-shaped widget into one CSV.

The output is one CSV **per report**. Each table-shaped widget's rows
are concatenated with a leading ``widget_id`` / ``widget_title`` /
``widget_type`` column so a spreadsheet consumer can slice by widget.
Widgets that do not carry rows (query_value / free_text / group / ...)
emit one row with the flattened ``data`` as a JSON blob so nothing is
silently dropped.

The header row is the union of every column across the touched
widgets - stable across renders because column order is derived from
first appearance.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget

_TABLE_WIDGET_TYPES: frozenset[str] = frozenset({"table", "top_list"})
_LEADING_COLUMNS: tuple[str, ...] = (
    "widget_id",
    "widget_title",
    "widget_type",
)


class CsvFormatEncoder:
    """Serialize a :class:`RenderedReport` to a UTF-8 CSV body."""

    name = "csv"
    content_type = "text/csv; charset=utf-8"

    def encode(self, report: RenderedReport) -> bytes:
        widgets = list(_iter_widgets(report.widgets))
        columns = self._collect_columns(widgets)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for widget in widgets:
            for row in self._widget_rows(widget):
                writer.writerow(row)
        return buffer.getvalue().encode("utf-8")

    @staticmethod
    def _collect_columns(widgets: Sequence[RenderedWidget]) -> tuple[str, ...]:
        seen: dict[str, None] = {name: None for name in _LEADING_COLUMNS}
        for widget in widgets:
            if widget.type in _TABLE_WIDGET_TYPES:
                for col in widget.data.get("columns") or ():
                    seen[str(col)] = None
            else:
                seen["value"] = None
        return tuple(seen)

    @staticmethod
    def _widget_rows(widget: RenderedWidget) -> list[dict[str, Any]]:
        leading: dict[str, Any] = {
            "widget_id": widget.id,
            "widget_title": widget.title,
            "widget_type": widget.type,
        }
        if widget.type in _TABLE_WIDGET_TYPES:
            columns = widget.data.get("columns") or ()
            out: list[dict[str, Any]] = []
            for row in widget.data.get("rows") or ():
                merged: dict[str, Any] = dict(leading)
                for col in columns:
                    merged[str(col)] = _stringify(row.get(col))
                out.append(merged)
            if not out:
                return [dict(leading)]
            return out
        return [
            {
                **leading,
                "value": _stringify(_shallow_summary(widget.data)),
            }
        ]


def _iter_widgets(widgets: Sequence[RenderedWidget]) -> list[RenderedWidget]:
    ordered: list[RenderedWidget] = []
    for widget in widgets:
        ordered.append(widget)
        if widget.children:
            ordered.extend(_iter_widgets(widget.children))
    return ordered


def _shallow_summary(data: Mapping[str, Any]) -> Any:
    if "value" in data:
        return data["value"]
    return json.dumps(dict(data), ensure_ascii=False)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


__all__ = ["CsvFormatEncoder"]
