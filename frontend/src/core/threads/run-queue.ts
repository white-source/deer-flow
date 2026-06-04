import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

export type EnqueuedRunResponse = {
  run_id: string;
  thread_id: string;
  status: string;
  queue_position?: number | null;
};

export type SubmitEnqueueResult =
  | { kind: "queued"; runId: string; queuePosition: number | null }
  | { kind: "streaming"; runId: string };

export type RunSummary = {
  status?: string;
};

/** Stream modes used for both submit and join on queued runs. */
export const THREAD_RUN_STREAM_MODES = [
  "values",
  "messages-tuple",
  "custom",
] as const;

const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
]);

export async function fetchRun(
  threadId: string,
  runId: string,
): Promise<RunSummary | null> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}`,
    { method: "GET" },
  );
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as RunSummary;
}

export async function waitUntilRunJoinable(
  threadId: string,
  runId: string,
  options?: { maxAttempts?: number; intervalMs?: number },
): Promise<void> {
  const maxAttempts = options?.maxAttempts ?? 600;
  const intervalMs = options?.intervalMs ?? 100;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const run = await fetchRun(threadId, runId);
    const status = run?.status;
    if (status && status !== "queued") {
      if (status === "pending" || status === "running") {
        return;
      }
      if (TERMINAL_RUN_STATUSES.has(status)) {
        throw new Error(
          `Run ${runId} finished before its stream could be joined (${status})`,
        );
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(`Timed out waiting for run ${runId} to leave the queue`);
}

export function adjustQueueDepth(
  current: number,
  delta: number,
): number {
  return Math.max(0, current + delta);
}

export async function countQueuedRuns(threadId: string): Promise<number> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs`,
    {
      method: "GET",
    },
  );
  if (!response.ok) {
    return 0;
  }
  const runs = (await response.json()) as Array<{ status?: string }>;
  return runs.filter((run) => run.status === "queued").length;
}

export async function submitEnqueuedRun(
  threadId: string,
  body: Record<string, unknown>,
): Promise<SubmitEnqueueResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        ...body,
        multitask_strategy: "enqueue",
      }),
    },
  );

  if (response.status === 202) {
    const payload = (await response.json()) as EnqueuedRunResponse;
    return {
      kind: "queued",
      runId: payload.run_id,
      queuePosition: payload.queue_position ?? null,
    };
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Failed to enqueue run (${response.status})`);
  }

  const location = response.headers.get("content-location") ?? "";
  const match = /\/runs\/([^/]+)/.exec(location);
  return {
    kind: "streaming",
    runId: match?.[1] ?? "",
  };
}
