import { beforeEach, describe, expect, it, vi } from "vitest";

const { useMutationMock } = vi.hoisted(() => ({
  useMutationMock: vi.fn((options) => options),
}));

const { resumeRevisionMock, injectRevisionMock, switchActiveRevisionMock } =
  vi.hoisted(() => ({
    resumeRevisionMock: vi.fn(),
    injectRevisionMock: vi.fn(),
    switchActiveRevisionMock: vi.fn(),
  }));

vi.mock("@tanstack/react-query", () => ({
  useMutation: useMutationMock,
}));

vi.mock("@/core/revisions/api", () => ({
  resumeRevision: resumeRevisionMock,
  injectRevision: injectRevisionMock,
  switchActiveRevision: switchActiveRevisionMock,
}));

describe("revisions hooks", () => {
  beforeEach(() => {
    useMutationMock.mockClear();
    resumeRevisionMock.mockReset();
    injectRevisionMock.mockReset();
    switchActiveRevisionMock.mockReset();
  });

  it("useInjectRevision wires mutationFn to injectRevision", async () => {
    const { useInjectRevision } = await import("@/core/revisions/hooks");
    const mutation = useInjectRevision() as unknown as {
      mutationFn: (args: { revisionId: string; instruction: string }) => unknown;
    };

    await mutation.mutationFn({ revisionId: "rev-1", instruction: "switch" });
    expect(injectRevisionMock).toHaveBeenCalledWith("rev-1", "switch");
  });

  it("useResumeRevision wires mutationFn to resumeRevision", async () => {
    const { useResumeRevision } = await import("@/core/revisions/hooks");
    const mutation = useResumeRevision() as unknown as {
      mutationFn: (args: { revisionId: string }) => unknown;
    };

    await mutation.mutationFn({ revisionId: "rev-1" });
    expect(resumeRevisionMock).toHaveBeenCalledWith("rev-1");
  });

  it("useSwitchActiveRevision wires mutationFn to switchActiveRevision", async () => {
    const { useSwitchActiveRevision } = await import("@/core/revisions/hooks");
    const mutation = useSwitchActiveRevision() as unknown as {
      mutationFn: (args: { threadId: string; revisionId: string }) => unknown;
    };

    await mutation.mutationFn({ threadId: "thread-1", revisionId: "rev-1" });
    expect(switchActiveRevisionMock).toHaveBeenCalledWith("thread-1", "rev-1");
  });
});