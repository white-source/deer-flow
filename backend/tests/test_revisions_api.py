"""Tests for revision action API endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import revisions


def _make_app(registry):
    app = make_authed_test_app()
    app.include_router(revisions.router)
    app.state.revision_registry = registry
    return app


def test_resume_allows_transition_to_running():
    registry = MagicMock()
    registry.transition_revision = AsyncMock(return_value=SimpleNamespace(revision_id="rev-1", status="running"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/runs/rev-1/resume")

    assert response.status_code == 200
    assert response.json() == {"revision_id": "rev-1", "status": "running"}
    registry.transition_revision.assert_awaited_once_with("rev-1", "running")


def test_resume_rejects_invalid_state_transition():
    registry = MagicMock()
    registry.transition_revision = AsyncMock(side_effect=ValueError("superseded -> running is not allowed"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/runs/rev-1/resume")

    assert response.status_code == 409
    assert "superseded -> running" in response.json()["detail"]


def test_inject_creates_new_revision():
    registry = MagicMock()
    registry.fork_revision = AsyncMock(
        return_value=SimpleNamespace(
            revision_id="rev-2",
            supersedes_revision_id="rev-1",
            status="pending",
            checkpoint_namespace="run:root-1:rev:rev-2",
        )
    )

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/runs/rev-1/inject", json={"instruction": "switch plan"})

    assert response.status_code == 200
    body = response.json()
    assert body["revision_id"] == "rev-2"
    assert body["superseded_revision_id"] == "rev-1"
    assert body["status"] == "pending"
    assert body["checkpoint_namespace"] == "run:root-1:rev:rev-2"
    registry.fork_revision.assert_awaited_once_with(
        parent_revision_id="rev-1", reason="switch plan", mode="continue"
    )


def test_inject_returns_404_when_revision_missing():
    registry = MagicMock()
    registry.fork_revision = AsyncMock(side_effect=ValueError("revision not found: rev-missing"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/runs/rev-missing/inject", json={"instruction": "switch plan"})

    assert response.status_code == 404
    assert "revision not found" in response.json()["detail"]


def test_switch_active_run_success():
    registry = MagicMock()
    registry.switch_active_revision = AsyncMock(return_value=None)

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/threads/thread-1/active-run", json={"revision_id": "rev-2"})

    assert response.status_code == 200
    assert response.json() == {"thread_id": "thread-1", "active_revision_id": "rev-2"}
    registry.switch_active_revision.assert_awaited_once_with(
        thread_id="thread-1",
        revision_id="rev-2",
    )


def test_switch_active_run_rejects_mismatched_thread():
    registry = MagicMock()
    registry.switch_active_revision = AsyncMock(side_effect=ValueError("revision not found"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/threads/thread-1/active-run", json={"revision_id": "rev-2"})

    assert response.status_code == 404
    assert "revision not found" in response.json()["detail"]


def test_switch_active_run_returns_404_when_revision_missing():
    registry = MagicMock()
    registry.switch_active_revision = AsyncMock(side_effect=ValueError("revision not found: rev-missing"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/threads/thread-1/active-run", json={"revision_id": "rev-missing"})

    assert response.status_code == 404
    assert "revision not found" in response.json()["detail"]


def test_switch_active_run_maps_set_active_errors_to_conflict():
    registry = MagicMock()
    registry.switch_active_revision = AsyncMock(side_effect=ValueError("revision rev-2 not active candidate under root root-1"))

    app = _make_app(registry)
    with TestClient(app) as client:
        response = client.post("/api/threads/thread-1/active-run", json={"revision_id": "rev-2"})

    assert response.status_code == 409
    assert "not active candidate" in response.json()["detail"]


def test_missing_registry_returns_503():
    app = make_authed_test_app()
    app.include_router(revisions.router)

    with TestClient(app) as client:
        response = client.post("/api/runs/rev-1/resume")

    assert response.status_code == 503
    assert response.json()["detail"] == "Revision registry not available"
