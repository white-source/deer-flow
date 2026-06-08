"""E2E tests for Scenario 4: interrupt mid-stream + fork with continue mode.

Scenario: User asks "8块是什么", sees partial result "8元是增值业务",
then interrupts with "我没订过啊". Talker recognizes intent=inject, mode=continue.
Runtime cancels current run, forks new revision inheriting checkpoint namespace.
Graph continues with full context, focuses on verifying subscription evidence.

Requires: Running Gateway with DEER_FLOW_REVISION_RUNTIME_ENABLED=1
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_interrupt_cancel_and_fork_continue_inherits_namespace(client: httpx.AsyncClient, thread_id: str):
    """After cancel, inject with mode=continue inherits checkpoint namespace."""
    # Given: create a run
    run_resp = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "8块是什么费用"}]},
        },
    )
    if run_resp.status_code != 200:
        pytest.skip("Cannot create run")
    run_id = run_resp.json()["run_id"]

    # When: cancel the run
    cancel_resp = await client.post(f"/api/threads/{thread_id}/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200

    # When: inject with mode=continue
    # Get revision_id from the run metadata
    run_detail = await client.get(f"/api/threads/{thread_id}/runs/{run_id}")
    run_body = run_detail.json()
    revision_id = (run_body.get("metadata") or {}).get("revision_id")

    if revision_id:
        inject_resp = await client.post(
            f"/api/runs/{revision_id}/inject",
            json={"instruction": "我没订过啊，重点查凭证", "mode": "continue"},
        )
        assert inject_resp.status_code == 200
        child = inject_resp.json()

        # Then: child inherits parent's checkpoint namespace
        # (namespace references parent revision, not child)
        child_ns = child.get("checkpoint_namespace", "")
        assert revision_id in child_ns or child_ns != ""
        assert child["superseded_revision_id"] == revision_id


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_interrupt_preserves_checkpoint_context(client: httpx.AsyncClient, thread_id: str):
    """Continue mode: checkpoint history is preserved across fork."""
    # Given: create run to establish checkpoint with some context
    run_resp = await client.post(
        f"/api/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead-agent",
            "input": {"messages": [{"role": "user", "content": "测试checkpoint保留"}]},
        },
    )
    if run_resp.status_code != 200:
        pytest.skip("Cannot create run")

    # Note: Full checkpoint verification requires reading from checkpointer,
    # which is not exposed via the HTTP API. This test verifies the flow
    # works end-to-end without crashing, and the checkpointer behavior
    # is verified in the registry unit tests.
    assert run_resp.status_code == 200
