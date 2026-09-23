"""Workflow recording is optional; workflow errors are never suppressed."""
from .core import Run, capture, current_run

__all__ = ["Run", "capture", "current_run"]
__version__ = "0.1.0"
