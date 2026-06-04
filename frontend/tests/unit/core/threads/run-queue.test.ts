import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWithAuth } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

describe("run-queue", () => {
  beforeEach(() => {
    fetchWithAuth.mockReset();
  });

  it("adjustQueueDepth never goes below zero", async () => {
    const { adjustQueueDepth } = await import("@/core/threads/run-queue");
    expect(adjustQueueDepth(1, -1)).toBe(0);
    expect(adjustQueueDepth(0, -3)).toBe(0);
  });

  it("adjustQueueDepth increments queued depth", async () => {
    const { adjustQueueDepth } = await import("@/core/threads/run-queue");
    expect(adjustQueueDepth(2, 1)).toBe(3);
  });

  it("submitEnqueuedRun uses auth fetch for POST stream", async () => {
    fetchWithAuth.mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({
        run_id: "run-1",
        thread_id: "thread-1",
        status: "queued",
        queue_position: 1,
      }),
    });

    const { submitEnqueuedRun } = await import("@/core/threads/run-queue");

    await expect(
      submitEnqueuedRun("thread-1", { assistant_id: "lead_agent" }),
    ).resolves.toEqual({
      kind: "queued",
      runId: "run-1",
      queuePosition: 1,
    });

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/api/threads/thread-1/runs/stream"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        }),
      }),
    );
  });

  it("waitUntilRunJoinable resolves when run leaves queued", async () => {
    fetchWithAuth
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "queued" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "running" }),
      });

    const { waitUntilRunJoinable } = await import("@/core/threads/run-queue");

    await expect(
      waitUntilRunJoinable("thread-1", "run-1", {
        intervalMs: 0,
        maxAttempts: 5,
      }),
    ).resolves.toBeUndefined();
  });

  it("waitUntilRunJoinable rejects when run finishes before join", async () => {
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ status: "success" }),
    });

    const { waitUntilRunJoinable } = await import("@/core/threads/run-queue");

    await expect(
      waitUntilRunJoinable("thread-1", "run-1", {
        intervalMs: 0,
        maxAttempts: 2,
      }),
    ).rejects.toThrow(/finished before its stream could be joined/);
  });
});
