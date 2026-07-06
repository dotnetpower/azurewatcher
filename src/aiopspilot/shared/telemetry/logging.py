"""Structured JSON logging with ``correlation_id`` auto-injection.

Design rules (see ``coding-conventions.instructions.md``):

- Emit **JSON, one object per line** - machines parse, humans grep.
- Every line carries an ISO 8601 UTC timestamp, log level, logger name,
  message, and - when set - ``correlation_id`` from
  :mod:`aiopspilot.shared.telemetry.correlation`.
- Never dump raw event payloads or secrets. Callers pass structured
  ``extra`` dicts that they have already redacted.
- ``configure_logging`` is idempotent so a re-entered composition root
  does not stack handlers.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TextIO

from .correlation import current_correlation_id

if TYPE_CHECKING:
    from collections.abc import Mapping


class JsonFormatter(logging.Formatter):
    """One JSON object per :class:`logging.LogRecord`."""

    # Attributes on LogRecord that ``logging`` sets by default; anything
    # else in ``record.__dict__`` was added via ``logger.info(..., extra=...)``
    # and should show up in the emitted line.
    _RESERVED = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": current_correlation_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            payload[k] = v

        return json.dumps(payload, ensure_ascii=True, default=str)


_HANDLER_MARKER = "_aiopspilot_json_handler"


def configure_logging(
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
) -> None:
    """Wire the root logger to emit JSON on ``stream`` (default: stdout).

    Idempotent: repeated calls replace the previous handler, they do not
    stack. That matters because a fork's entry point may call the
    composition root more than once.
    """
    root = logging.getLogger()
    root.setLevel(level)

    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger with the JSON formatter already attached."""
    return logging.getLogger(name)


def log_extra(**fields: Any) -> Mapping[str, Any]:
    """Small helper so callers write ``logger.info(msg, extra=log_extra(k=v))``.

    Not strictly required - plain ``dict`` works - but keeps call sites
    grep-friendly.
    """
    return dict(fields)


__all__ = ["JsonFormatter", "configure_logging", "get_logger", "log_extra"]
