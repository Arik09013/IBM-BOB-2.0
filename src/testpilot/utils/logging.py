"""
Structured logging utilities for TestPilot AI.

Provides:
- A get_logger() factory that attaches a run_id to every log record.
- A JSONL session log writer for reproducible experiment traces.
- Log level control from Settings.

Design note: API keys and secrets must never be passed to logging calls.
The log format is deliberately machine-parseable for research use.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Custom formatter — includes run_id in every line
# ---------------------------------------------------------------------------

class _RunIdFormatter(logging.Formatter):
    """Formatter that injects a run_id field into every log record."""

    def __init__(self, run_id: str = "unset", *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        record.run_id = self.run_id
        return super().format(record)


_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] [run:%(run_id)s] %(name)s — %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def get_logger(
    name: str,
    *,
    run_id: str = "unset",
    level: str = "INFO",
) -> logging.Logger:
    """
    Return a Logger named *name* configured for TestPilot output.

    Parameters
    ----------
    name:
        Logger name, typically ``__name__`` of the calling module.
    run_id:
        The unique identifier for the current pipeline run.
        Injected into every log line for traceability.
    level:
        Log level string ("DEBUG", "INFO", "WARNING", "ERROR").
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level.upper())
    handler.setFormatter(_RunIdFormatter(run_id=run_id, fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)

    return logger


# ---------------------------------------------------------------------------
# Root-level setup — called once at CLI startup
# ---------------------------------------------------------------------------

def configure_root_logging(level: str = "INFO", run_id: str = "unset") -> None:
    """
    Configure the root logger for the entire TestPilot process.

    Should be called once in cli.py before any other module is imported.
    """
    root = logging.getLogger("testpilot")
    root.setLevel(level.upper())

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            _RunIdFormatter(run_id=run_id, fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        root.addHandler(handler)


# ---------------------------------------------------------------------------
# JSONL session logger — for reproducible experiment traces
# ---------------------------------------------------------------------------

class SessionLogger:
    """
    Appends structured JSON log entries to a per-run JSONL file.

    Each entry is one JSON object per line, making the file easy to parse
    with standard tools (jq, pandas, etc.) for research analysis.

    Note: This logger must never receive secrets or API keys.
    """

    def __init__(self, log_path: Path, run_id: str) -> None:
        self.log_path = log_path
        self.run_id = run_id
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = log_path.open("a", encoding="utf-8")

    def log(self, event: str, data: dict[str, Any]) -> None:
        """Append a structured event entry to the JSONL file."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **data,
        }
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        """Flush and close the underlying file handle."""
        self._file.flush()
        self._file.close()

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
