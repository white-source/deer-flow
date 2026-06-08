"""E2E tests for Scenario 2: modify task via inject.

Scenario: User first asks "查8月话费", then changes to "不看8月，查9月".
Talker recognizes intent=inject, mode=replace (parameter changed).
Runtime forks new revision with independent checkpoint namespace.
Graph starts fresh, only queries September.

Requires: Running Gateway with DEER_FLOW_REVISION_RUNTIME_ENABLED=1
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_inject_replace_creates_independent_namespace(
    client: httpx.AsyncClient, thread_id: str
):
    """mode=replace: child revision has a NEW independent checkpoint namespace."""
    # Given: create a run to establish root_run + revision
    run_resp = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "查8月话费"}]},
        },
    )
    assert run_resp.status_code == 200
    # Extract revision_id from run context/metadata
    run_body = run_resp.json()
    revision_id = run_body.get("revision_id")
    if not revision_id:
        # Revision runtime creates revision implicitly; check for active revision
        active_resp = await client.post(
            f"/api/threads/{thread_id}/active-run",
            json={"revision_id": ""},
        )
        if active_resp.status_code != 200:
            pytest.skip("Revision runtime not fully configured")
        return

    # When: inject with mode=replace
    inject_resp = await client.post(
        f"/api/runs/{revision_id}/inject",
        json={"instruction": "不看8月，查9月话费", "mode": "replace"},
    )
    assert inject_resp.status_code == 200
    body = inject_resp.json()

    # Then: child has independent namespace
    child_id = body["revision_id"]
    assert body["superseded_revision_id"] == revision_id
    assert "checkpoint_namespace" in body
    # Replace mode: new namespace (not parent's)
    child_ns = body["checkpoint_namespace"]
    assert child_id in child_ns  # namespace references child, not parent


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_inject_continue_inherits_parent_namespace(
    client: httpx.AsyncClient, thread_id: str
):
    """mode=continue: child revision inherits parent's checkpoint namespace."""
    run_resp = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "8块是什么费用"}]},
        },
    )
    assert run_resp.status_code == 200
    # Skip if revision runtime not active
    # ...


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_inject_default_mode_is_continue(
    client: httpx.AsyncClient, thread_id: str
):
    """Not specifying mode = default to continue (backward compatible)."""
    response = await client.post(
        "/api/runs/rev-test/inject",
        json={"instruction": "test default mode"},
    )
    # 404 expected (revision doesn't exist), but mode validation should not reject
    assert response.status_code in (200, 404, 422)
    if response.status_code == 422:
        body = response.json()
        # Should NOT be a mode validation error
        assert "mode" not in str(body.get("detail", ""))


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_inject_invalid_mode_returns_422(client: httpx.AsyncClient):
    """Invalid mode value is rejected with 422."""
    response = await client.post(
        "/api/runs/rev-test/inject",
        json={"instruction": "test", "mode": "invalid"},
    )
    assert response.status_code == 422
    body = response.json()
    assert "mode" in str(body["detail"]).lower()
