"""Shared fixtures for revision E2E tests.

These tests require a running Gateway with:
    DEER_FLOW_REVISION_RUNTIME_ENABLED=1

Start the Gateway before running:
    cd backend && DEER_FLOW_REVISION_RUNTIME_ENABLED=1 make gateway

Then run E2E tests:
    cd backend && PYTHONPATH=. uv run pytest tests/e2e/ -v -m e2e
"""

from __future__ import annotations

import os

import httpx
import pytest


@pytest.fixture(autouse=True)
def _require_e2e_gateway():
    """Skip E2E tests when the Gateway is not running."""
    base_url = os.environ.get("GATEWAY_TEST_URL", "http://localhost:8001")
    try:
        import socket

        host = base_url.split("://")[1].split(":")[0]
        port = int(base_url.split(":")[-1])
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        if result != 0:
            pytest.skip(f"Gateway not reachable at {base_url}")
    except Exception:
        pytest.skip(f"Gateway not reachable at {base_url}")


@pytest.fixture
async def client():
    """HTTPX async client connected to the running Gateway."""
    base_url = os.environ.get("GATEWAY_TEST_URL", "http://localhost:8001")
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(30.0)) as ac:
        yield ac


@pytest.fixture
async def thread_id(client: httpx.AsyncClient) -> str:
    """Create a test thread and return its ID."""
    response = await client.post("/api/threads", json={"metadata": {"test": True}})
    if response.status_code != 200:
        pytest.skip(f"Failed to create thread: {response.text}")
    return response.json()["thread_id"]
