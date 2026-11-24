"""Structured logging via structlog."""

from __future__ import annotations

import logging
import sys
from typing import IO

import structlog


def setup_logging(level: str = "INFO", *, stream: IO[str] | None = None) -> None:
    """Configure structlog with sensible defaults.

    Args:
        level: log level name
        stream: where to write logs. Defaults to stdout. Pass `sys.stderr`
            for MCP stdio servers (stdout is reserved for JSON-RPC).
    """
    out = stream if stream is not None else sys.stdout
    is_tty = hasattr(out, "isatty") and out.isatty()

    logging.basicConfig(
        format="%(message)s",
        stream=out,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=is_tty),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=out),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
