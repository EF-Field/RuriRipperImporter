"""Structured diagnostics for evidence-gated runtime contracts.

Runtime-contract decisions must always be observable. Successful decisions emit
INFO; unresolved evidence, disabled modules, rejected evidence and retained
engine gaps emit WARNING. Callers also receive the structured event so logging
configuration never becomes the only record of a decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from typing import Any, Mapping


LOGGER_NAME = "endfield_animation.runtime_contract"
logger = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class DiagnosticEvent:
    level: str
    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def emit(level: int, code: str, message: str, **context: Any) -> DiagnosticEvent:
    """Emit and return one structured INFO/WARNING contract event."""
    if level not in (logging.INFO, logging.WARNING):
        raise ValueError("runtime-contract diagnostics must use INFO or WARNING")
    event = DiagnosticEvent(logging.getLevelName(level), code, message, dict(context))
    logger.log(level, "%s", json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
    return event


def info(code: str, message: str, **context: Any) -> DiagnosticEvent:
    return emit(logging.INFO, code, message, **context)


def warning(code: str, message: str, **context: Any) -> DiagnosticEvent:
    return emit(logging.WARNING, code, message, **context)
