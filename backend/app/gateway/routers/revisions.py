"""Revision action endpoints for resume/inject/active-run switching."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_revision_registry

router = APIRouter(prefix="/api", tags=["revisions"])


class InjectRequest(BaseModel):
    instruction: str = Field(default="inject", min_length=1)


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
    """Fork a new revision and supersede the supplied revision."""
    registry = get_revision_registry(request)
    try:
        forked = await registry.fork_revision(parent_revision_id=revision_id, reason=body.instruction)
    except ValueError as exc:
        _map_registry_error(exc)
    return {
        "revision_id": forked.revision_id,
        "superseded_revision_id": forked.supersedes_revision_id,
        "status": forked.status,
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
