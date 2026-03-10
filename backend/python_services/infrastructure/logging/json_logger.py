from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any


def get_logger(name: str = "lexicon_pipeline") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _default_json(value: Any) -> Any:
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def log_event(
    logger: logging.Logger,
    *,
    level: int = logging.INFO,
    event: str,
    **fields: Any,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    logger.log(level, json.dumps(payload, default=_default_json, ensure_ascii=True))
