"""Logging setup. Call `configure_logging()` once at process entry."""

from __future__ import annotations

import logging

from insights.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure root logging from settings.log_level (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for `name`."""
    configure_logging()
    return logging.getLogger(name)
