import { useMutation } from "@tanstack/react-query";

import { injectRevision, resumeRevision, switchActiveRevision } from "./api";

export function useResumeRevision() {
  return useMutation({
    mutationFn: ({ revisionId }: { revisionId: string }) =>
      resumeRevision(revisionId),
  });
}

export function useInjectRevision() {
  return useMutation({
    mutationFn: ({
      revisionId,
      instruction,
    }: {
      revisionId: string;
      instruction: string;
    }) => injectRevision(revisionId, instruction),
  });
}

export function useSwitchActiveRevision() {
  return useMutation({
    mutationFn: ({
      threadId,
      revisionId,
    }: {
      threadId: string;
      revisionId: string;
    }) => switchActiveRevision(threadId, revisionId),
  });
}