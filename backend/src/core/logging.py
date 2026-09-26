"""Structured logging for Google Cloud operations and local development."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class GoogleCloudJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON adhering to Google Cloud Logging schema."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Propagate custom context (e.g. project_id, job_id, trace_id)
        if hasattr(record, "job_id"):
            log_entry["job_id"] = getattr(record, "job_id")
        if hasattr(record, "project_id"):
            log_entry["project_id"] = getattr(record, "project_id")
        if hasattr(record, "extra_data"):
            log_entry["data"] = getattr(record, "extra_data")

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logger(name: str = "vibeshorts", level: int = logging.INFO) -> logging.Logger:
    """Configures and returns a structured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if re-initialized
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(GoogleCloudJsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = setup_logger()
