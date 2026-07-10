"""JSON format encoder - the default, canonical FE contract."""

from __future__ import annotations

import json

from fdai.core.reporting.models import RenderedReport


class JsonFormatEncoder:
    """Serialize a :class:`RenderedReport` to compact UTF-8 JSON bytes.

    ``ensure_ascii=False`` keeps non-ASCII content (e.g. proper nouns)
    intact instead of escaping every character. The engine does not
    place user-controlled Hangul into an L0 audit surface (that stays
    English by policy), but a report title / label carrying non-ASCII
    proper nouns should not be double-encoded.
    """

    name = "json"
    content_type = "application/json"

    def encode(self, report: RenderedReport) -> bytes:
        payload = report.to_dict()
        return json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False, sort_keys=False
        ).encode("utf-8")


__all__ = ["JsonFormatEncoder"]
