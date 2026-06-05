"""Revision status enums."""

from enum import StrEnum


class RevisionStatus(StrEnum):
    """Lifecycle status of a single revision."""

    pending = "pending"
    running = "running"
    awaiting_action = "awaiting_action"
    paused = "paused"
    superseded = "superseded"
    completed = "completed"
    cancelled = "cancelled"
    error = "error"
