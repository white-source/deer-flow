"""Helpers for coordinating revision-aware run execution."""

from __future__ import annotations


def build_checkpoint_namespace(root_run_id: str, revision_id: str) -> str:
    """Return the checkpoint namespace for a revision within a root run."""
    return f"run:{root_run_id}:rev:{revision_id}"
