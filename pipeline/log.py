"""Strukturált naplózás.

A repó publikus, tehát az Actions-napló is az (spec/05, 1. fejezet): a
naplóba csak darabszám, forrásnév és hibaüzenet kerülhet — árfolyam, kulcs
vagy felhasználói adat soha.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure(level: int = logging.INFO) -> None:
    """Egysoros, kulcs=érték alakú napló a stderr-re."""
    logging.basicConfig(stream=sys.stderr, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.KeyValueRenderer(key_order=["timestamp", "level", "event"]),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
