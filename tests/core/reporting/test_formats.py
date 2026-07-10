"""Format-encoder tests."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from fdai.core.reporting.formats import (
    CsvFormatEncoder,
    JsonFormatEncoder,
    MarkdownFormatEncoder,
    default_format_encoders,
    install_default_formats,
)
from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.core.reporting.registry import FormatRegistry


def _report() -> RenderedReport:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    return RenderedReport(
        id="ops",
        version="1.0.0",
        name="Ops Overview",
        description="Daily ops KPIs.",
        generated_at=now,
        time_range=(now - timedelta(hours=1), now),
        variables={"env": "prod"},
        widgets=(
            RenderedWidget(
                id="events",
                type="query_value",
                title="Events (1h)",
                data={"value": 1200, "unit": "events"},
            ),
            RenderedWidget(
                id="top",
                type="top_list",
                title="Top rules",
                data={
                    "columns": ["rule", "value"],
                    "rows": [
                        {"rule": "cost.idle_vm", "value": 12},
                        {"rule": "sec.public_kv", "value": 7},
                    ],
                },
            ),
            RenderedWidget(
                id="broken",
                type="table",
                title="Broken",
                data={},
                error="datasource error: RuntimeError: boom",
            ),
        ),
        tags=("ops",),
    )


class TestJsonFormat:
    def test_content_type(self) -> None:
        assert JsonFormatEncoder().content_type == "application/json"

    def test_encodes_report_to_json(self) -> None:
        body = JsonFormatEncoder().encode(_report())
        payload = json.loads(body.decode("utf-8"))
        assert payload["id"] == "ops"
        assert payload["widgets"][2]["error"].startswith("datasource error")


class TestMarkdownFormat:
    def test_renders_headings_and_body(self) -> None:
        body = MarkdownFormatEncoder().encode(_report()).decode("utf-8")
        assert body.startswith("# Ops Overview\n")
        assert "## Events (1h)" in body
        assert "**1200 events**" in body
        # Top list rendered as a markdown table.
        assert "| rule | value |" in body
        assert "| cost.idle_vm | 12 |" in body
        # Error widget rendered as blockquote, not a code block.
        assert "> ERROR: datasource error" in body

    def test_ascii_only_punctuation(self) -> None:
        body = MarkdownFormatEncoder().encode(_report()).decode("utf-8")
        # Language policy: no smart quotes, ellipsis, em/en dash, NBSP.
        for banned in ("\u2014", "\u2013", "\u2026", "\u201c", "\u201d", "\u00a0"):
            assert banned not in body


class TestCsvFormat:
    def test_headers_and_rows(self) -> None:
        body = CsvFormatEncoder().encode(_report()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
        header = reader.fieldnames or []
        assert set(header) >= {
            "widget_id",
            "widget_title",
            "widget_type",
            "rule",
            "value",
        }
        by_widget: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_widget.setdefault(row["widget_id"], []).append(row)
        # The top-list widget contributes 2 rows.
        assert len(by_widget["top"]) == 2
        # The scalar widget flattens to one row with the value.
        assert by_widget["events"][0]["value"] == "1200"


class TestFormatRegistry:
    def test_defaults_registered_by_name(self) -> None:
        names = {e.name for e in default_format_encoders()}
        assert names == {"json", "markdown", "csv"}

    def test_install_default_formats_is_idempotent(self) -> None:
        registry = FormatRegistry()
        install_default_formats(registry)
        install_default_formats(registry)  # re-install must not fail
        assert set(registry.names()) == {"csv", "json", "markdown"}
