"""One invocation-wide deadline shared with the installed drafting child."""

from __future__ import annotations

import os
import time

from .model_runtime import ModelTimeoutError


DEADLINE_ENV = "LINKEDIN_OS_GLOBAL_DEADLINE_EPOCH"


class GlobalDeadlineExceeded(ModelTimeoutError):
    """The approved shared daily budget expired, rather than one model stage."""


def deadline_epoch() -> float | None:
    raw = os.environ.get(DEADLINE_ENV)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise GlobalDeadlineExceeded("Invalid global run deadline.") from exc
    if not 0 < value < float("inf"):
        raise GlobalDeadlineExceeded("Invalid global run deadline.")
    return value


def remaining_seconds() -> float | None:
    deadline = deadline_epoch()
    if deadline is None:
        return None
    remaining = deadline - time.time()
    if remaining <= 0:
        raise GlobalDeadlineExceeded("TIME_BUDGET_EXCEEDED: shared daily deadline expired.")
    return remaining


def bounded_timeout(requested: float) -> tuple[float, bool]:
    remaining = remaining_seconds()
    if remaining is None or requested <= remaining:
        return requested, False
    return remaining, True
