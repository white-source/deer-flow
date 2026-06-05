import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import type { RevisionActionResponse, SwitchActiveRevisionRequest } from "./types";

async function readRevisionResponse(
  response: Response,
  fallbackMessage: string,
): Promise<RevisionActionResponse> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || fallbackMessage);
  }

  return (await response.json()) as RevisionActionResponse;
}

export async function resumeRevision(
  revisionId: string,
): Promise<RevisionActionResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/runs/${encodeURIComponent(revisionId)}/resume`,
    {
      method: "POST",
    },
  );
  return readRevisionResponse(response, "Failed to resume revision.");
}

export async function injectRevision(
  revisionId: string,
  instruction: string,
): Promise<RevisionActionResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/runs/${encodeURIComponent(revisionId)}/inject`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ instruction }),
    },
  );
  return readRevisionResponse(response, "Failed to inject revision.");
}

export async function switchActiveRevision(
  threadId: string,
  revisionId: string,
): Promise<RevisionActionResponse> {
  const body: SwitchActiveRevisionRequest = { revision_id: revisionId };
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/active-run`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    },
  );
  return readRevisionResponse(
    response,
    "Failed to switch active revision.",
  );
}