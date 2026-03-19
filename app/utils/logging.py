"""
Structured logging setup.

Uses Python's standard logging configured with a JSON-friendly format
so logs are easy to ingest in Datadog / CloudWatch / Loki.
In development mode a more human-readable format is used instead.
"""

import logging
import sys

from app.config import settings

_HUMAN_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_JSON_FORMAT = (
    '{"time":"%(asctime)s","level":"%(levelname)s",'
    '"logger":"%(name)s","message":"%(message)s"}'
)


def configure_logging() -> None:
    """
    Call once at application startup.
    Child loggers inherit the root configuration.
    """
    fmt = _HUMAN_FORMAT if settings.app_env == "development" else _JSON_FORMAT
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    # Quieten noisy third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("git").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper — identical to logging.getLogger but signals intent."""
    return logging.getLogger(name)
