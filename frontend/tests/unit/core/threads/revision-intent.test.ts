import { expect, test } from "vitest";

import { resolveRevisionAction } from "@/core/threads/hooks";

test("resolveRevisionAction reads camelCase activeRevisionId", () => {
  expect(
    resolveRevisionAction({
      intent: "inject",
      activeRevisionId: "rev-1",
    }),
  ).toEqual({
    intent: "inject",
    activeRevisionId: "rev-1",
  });
});

test("resolveRevisionAction falls back to snake_case active_revision_id", () => {
  expect(
    resolveRevisionAction({
      intent: "resume",
      active_revision_id: "rev-2",
    }),
  ).toEqual({
    intent: "resume",
    activeRevisionId: "rev-2",
  });
});

test("resolveRevisionAction ignores empty values", () => {
  expect(
    resolveRevisionAction({
      intent: "",
      activeRevisionId: "",
      active_revision_id: "",
    }),
  ).toEqual({
    intent: undefined,
    activeRevisionId: undefined,
  });
});
