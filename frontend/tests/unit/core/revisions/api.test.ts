import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWithAuth } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

describe("revisions api", () => {
  beforeEach(() => {
    fetchWithAuth.mockReset();
  });

  it("inject targets /api/runs/{revision_id}/inject", async () => {
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ revision_id: "rev-2" }),
    });

    const { injectRevision } = await import("@/core/revisions/api");
    await injectRevision("rev-1", "switch plan");

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/api/runs/rev-1/inject"),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: "switch plan" }),
      }),
    );
  });

  it("resume targets /api/runs/{revision_id}/resume", async () => {
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ revision_id: "rev-1", status: "running" }),
    });

    const { resumeRevision } = await import("@/core/revisions/api");
    await resumeRevision("rev-1");

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/api/runs/rev-1/resume"),
      expect.objectContaining({
        method: "POST",
      }),
    );
  });

  it("switchActiveRevision targets /api/threads/{thread_id}/active-run", async () => {
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ revision_id: "rev-2" }),
    });

    const { switchActiveRevision } = await import("@/core/revisions/api");
    await switchActiveRevision("thread-1", "rev-2");

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/api/threads/thread-1/active-run"),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision_id: "rev-2" }),
      }),
    );
  });
});