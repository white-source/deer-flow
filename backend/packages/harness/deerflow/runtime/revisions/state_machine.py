"""Transition rules for revision status updates."""

from deerflow.runtime.revisions.schemas import RevisionStatus

ALLOWED_TRANSITIONS: dict[RevisionStatus, frozenset[RevisionStatus]] = {
    RevisionStatus.pending: frozenset(
        {
            RevisionStatus.running,
            RevisionStatus.cancelled,
        }
    ),
    RevisionStatus.running: frozenset(
        {
            RevisionStatus.awaiting_action,
            RevisionStatus.paused,
            RevisionStatus.superseded,
            RevisionStatus.completed,
            RevisionStatus.cancelled,
            RevisionStatus.error,
        }
    ),
    RevisionStatus.awaiting_action: frozenset(
        {
            RevisionStatus.running,
            RevisionStatus.superseded,
            RevisionStatus.cancelled,
            RevisionStatus.error,
        }
    ),
    RevisionStatus.paused: frozenset(
        {
            RevisionStatus.running,
            RevisionStatus.cancelled,
            RevisionStatus.error,
        }
    ),
    RevisionStatus.superseded: frozenset(),
    RevisionStatus.completed: frozenset(),
    RevisionStatus.cancelled: frozenset(),
    RevisionStatus.error: frozenset(),
}


def assert_transition_allowed(current: RevisionStatus, nxt: RevisionStatus) -> None:
    """Raise when the requested transition is not allowed by the state machine."""

    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(f"unknown revision status: {current}")
    if nxt not in allowed:
        raise ValueError(f"{current} -> {nxt} is not allowed")
