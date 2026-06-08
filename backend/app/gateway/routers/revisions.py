"""Revision action endpoints for resume/inject/active-run switching."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_revision_registry, get_run_manager
from deerflow.runtime.runs.schemas import RunStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["revisions"])


class InjectRequest(BaseModel):
    instruction: str = Field(default="inject", min_length=1)
    mode: str = Field(default="continue", pattern="^(replace|continue)$")


class SwitchActiveRequest(BaseModel):
    revision_id: str = Field(min_length=1)


def _map_registry_error(exc: ValueError) -> None:
    detail = str(exc)
    if "not found" in detail:
        raise HTTPException(status_code=404, detail=detail) from exc
    raise HTTPException(status_code=409, detail=detail) from exc


@router.post("/runs/{revision_id}/resume")
@require_permission("runs", "create")
async def resume_revision(revision_id: str, request: Request) -> dict:
    """Resume a paused/awaiting revision by transitioning to running."""
    registry = get_revision_registry(request)
    try:
        revision = await registry.transition_revision(revision_id, "running")
    except ValueError as exc:
        _map_registry_error(exc)
    return {"revision_id": revision.revision_id, "status": revision.status}


@router.post("/runs/{revision_id}/inject")
@require_permission("runs", "create")
async def inject_revision(revision_id: str, body: InjectRequest, request: Request) -> dict:
    """Fork a new revision and supersede the supplied revision.

    Cancels any inflight runs on the parent revision before forking so
    the old run does not continue executing alongside the new one.
    """
    registry = get_revision_registry(request)
    run_mgr = get_run_manager(request)

    # Cancel any inflight runs belonging to the parent revision before
    # forking, so the old graph execution stops and the queue advances.
    parent = await registry._repo.get_revision(revision_id)
    if parent is not None:
        root_run = await registry._repo.get_root_run(parent.root_run_id)
        if root_run is not None:
            try:
                runs = await run_mgr.list_by_thread(root_run.thread_id, limit=50)
            except Exception:
                runs = []
            for run in runs:
                run_revision_id = (run.metadata or {}).get("revision_id")
                if run_revision_id == revision_id and run.status in {
                    RunStatus.pending,
                    RunStatus.running,
                    RunStatus.queued,
                }:
                    try:
                        await run_mgr.cancel(run.run_id)
                        logger.info(
                            "Cancelled inflight run %s for revision %s before inject",
                            run.run_id,
                            revision_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to cancel run %s for revision %s",
                            run.run_id,
                            revision_id,
                            exc_info=True,
                        )

    try:
        forked = await registry.fork_revision(parent_revision_id=revision_id, reason=body.instruction, mode=body.mode)
    except ValueError as exc:
        _map_registry_error(exc)
    return {
        "revision_id": forked.revision_id,
        "superseded_revision_id": forked.supersedes_revision_id,
        "status": forked.status,
        "checkpoint_namespace": forked.checkpoint_namespace,
    }


@router.post("/threads/{thread_id}/active-run")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def switch_active_run(thread_id: str, body: SwitchActiveRequest, request: Request) -> dict:
    """Switch the active revision for a thread's root run."""
    registry = get_revision_registry(request)
    try:
        await registry.switch_active_revision(
            thread_id=thread_id,
            revision_id=body.revision_id,
        )
    except ValueError as exc:
        _map_registry_error(exc)

    return {
        "thread_id": thread_id,
        "active_revision_id": body.revision_id,
    }
