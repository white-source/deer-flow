"""Tests for revision status state-machine transitions."""

import pytest

from deerflow.runtime.revisions.schemas import RevisionStatus
from deerflow.runtime.revisions.state_machine import ALLOWED_TRANSITIONS, assert_transition_allowed


def test_running_to_awaiting_action_allowed():
    assert_transition_allowed(RevisionStatus.running, RevisionStatus.awaiting_action)


def test_superseded_to_running_blocked_with_expected_message():
    with pytest.raises(ValueError, match="superseded -> running is not allowed"):
        assert_transition_allowed(RevisionStatus.superseded, RevisionStatus.running)


@pytest.mark.parametrize(
    "current",
    [RevisionStatus.completed, RevisionStatus.cancelled, RevisionStatus.error],
)
def test_terminal_statuses_to_running_blocked(current: RevisionStatus):
    with pytest.raises(ValueError):
        assert_transition_allowed(current, RevisionStatus.running)


def test_every_status_has_transition_entry():
    assert set(ALLOWED_TRANSITIONS) == set(RevisionStatus)


@pytest.mark.parametrize(
    ("current", "nxt", "allowed"),
    [(current, nxt, nxt in ALLOWED_TRANSITIONS[current]) for current in RevisionStatus for nxt in RevisionStatus if current != nxt],
)
def test_transition_matrix(current: RevisionStatus, nxt: RevisionStatus, allowed: bool):
    if allowed:
        assert_transition_allowed(current, nxt)
    else:
        with pytest.raises(ValueError):
            assert_transition_allowed(current, nxt)


@pytest.mark.parametrize(
    "current",
    [
        RevisionStatus.running,
        RevisionStatus.paused,
        RevisionStatus.awaiting_action,
    ],
)
def test_non_terminal_to_cancelled_allowed(current: RevisionStatus):
    """User-initiated cancel should be allowed from running/paused/awaiting_action."""
    assert_transition_allowed(current, RevisionStatus.cancelled)


def test_pending_to_cancelled_allowed():
    """Cancel before first run starts should be allowed."""
    assert_transition_allowed(RevisionStatus.pending, RevisionStatus.cancelled)
