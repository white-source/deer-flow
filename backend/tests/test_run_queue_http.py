"""HTTP integration tests for enqueue multitask strategy."""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from deerflow.runtime.runs.schemas import RunStatus


_MINIMAL_CONFIG_YAML = """\
log_level: info
models:
  - name: fake-test-model
    display_name: Fake Test Model
    use: langchain_openai:ChatOpenAI
    model: gpt-4o-mini
sandbox:
  use: deerflow.community.local_sandbox.local_sandbox_provider:LocalSandboxProvider
  lazy_init: true
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
"""


@pytest.fixture
def isolated_deer_flow_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")
    staged_config = tmp_path / "config.yaml"
    staged_config.write_text(_MINIMAL_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(staged_config))
    return home


@pytest.fixture
def isolated_app(isolated_deer_flow_home: Path, monkeypatch: pytest.MonkeyPatch):
    from test_runtime_lifecycle_e2e import (
        _preserve_process_config_singletons,
        _reset_process_singletons,
    )

    _preserve_process_config_singletons(monkeypatch)
    _reset_process_singletons(monkeypatch)

    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(isolated_deer_flow_home / "db")

    from app.gateway.app import create_app

    return create_app()


def _register_user(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "queue-http@example.com", "password": "very-strong-password-123"},
    )
    assert response.status_code == 201, response.text
    csrf_token = client.cookies.get("csrf_token")
    assert csrf_token
    return csrf_token


def _create_thread(client: TestClient, csrf_token: str) -> str:
    thread_id = str(uuid.uuid4())
    response = client.post(
        "/api/threads",
        json={"thread_id": thread_id, "metadata": {}},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200, response.text
    return thread_id


def _run_body(**overrides) -> dict[str, Any]:
    body: dict[str, Any] = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": "queue test"}]},
        "config": {"recursion_limit": 50},
        "stream_mode": ["values"],
        "multitask_strategy": "enqueue",
    }
    body.update(overrides)
    return body


def _install_hold_launch(app, hold: threading.Event, release: threading.Event):
    dispatcher = app.state.run_dispatcher

    async def hold_launch(record, launch_ctx):
        async def _work() -> None:
            await launch_ctx.run_mgr.set_status(record.run_id, RunStatus.running)
            hold.set()
            while not release.is_set():
                await asyncio.sleep(0.05)
            await launch_ctx.run_mgr.set_status(record.run_id, RunStatus.success)
            await launch_ctx.run_mgr.notify_run_terminal(record.thread_id, record.run_id)

        record.task = asyncio.create_task(_work())

    dispatcher.launch = hold_launch


@pytest.mark.no_auto_user
def test_second_enqueue_run_returns_202(isolated_app):
    hold = threading.Event()
    release = threading.Event()

    with TestClient(isolated_app) as client:
        _install_hold_launch(isolated_app, hold, release)
        csrf = _register_user(client)
        thread_id = _create_thread(client, csrf)

        first = client.post(
            f"/api/threads/{thread_id}/runs",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf},
        )
        assert first.status_code == 200, first.text

        assert hold.wait(timeout=5), "first run did not reach running state"

        second = client.post(
            f"/api/threads/{thread_id}/runs/stream",
            json=_run_body(input={"messages": [{"role": "user", "content": "second"}]}),
            headers={"X-CSRF-Token": csrf},
        )
        assert second.status_code == 202, second.text
        payload = second.json()
        assert payload["status"] == "queued"
        assert payload["queue_position"] == 1

        release.set()


@pytest.mark.no_auto_user
def test_reject_strategy_still_returns_409(isolated_app):
    hold = threading.Event()
    release = threading.Event()

    with TestClient(isolated_app) as client:
        _install_hold_launch(isolated_app, hold, release)
        csrf = _register_user(client)
        thread_id = _create_thread(client, csrf)
        body = _run_body(multitask_strategy="reject")

        first = client.post(
            f"/api/threads/{thread_id}/runs",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )
        assert first.status_code == 200, first.text

        assert hold.wait(timeout=5), "first run did not start"

        second = client.post(
            f"/api/threads/{thread_id}/runs/stream",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )
        assert second.status_code == 409

        release.set()
