import { expect, test, type Route } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test("revision timeline renders and active badge updates from revision metadata", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let isLoggedIn = false;
  let streamCallCount = 0;

  await page.route("**/api/v1/auth/setup-status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ needs_setup: false }),
    });
  });

  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: isLoggedIn ? 200 : 401,
      contentType: "application/json",
      body: JSON.stringify(
        isLoggedIn
          ? { id: "user-1", email: "e2e@example.com" }
          : { detail: "Unauthorized" },
      ),
    });
  });

  await page.route("**/api/v1/auth/login/local", async (route) => {
    isLoggedIn = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "set-cookie":
          "access_token=e2e-token; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600",
      },
      body: JSON.stringify({ success: true }),
    });
  });

  const handleRevisionStream = async (route: Route) => {
    streamCallCount += 1;
    const revisions =
      streamCallCount === 1
        ? [
            {
              revision_id: "rev-1",
              label: "R1.0",
              status: "running",
            },
          ]
        : [
            {
              revision_id: "rev-1",
              label: "R1.0",
              status: "superseded",
            },
            {
              revision_id: "rev-2",
              label: "R1.1",
              status: "running",
            },
          ];
    const activeRevisionId = streamCallCount === 1 ? "rev-1" : "rev-2";

    const body = [
      {
        event: "metadata",
        data: {
          thread_id: MOCK_THREAD_ID,
          run_id: "run-rev-2",
        },
      },
      {
        event: "values",
        data: {
          revisions,
          active_revision_id: activeRevisionId,
          messages: [
            {
              type: "ai",
              id: `msg-ai-updated-${streamCallCount}`,
              content: "Revision metadata update",
              additional_kwargs: {
                active_revision_id: activeRevisionId,
                revisions,
              },
            },
          ],
        },
      },
      {
        event: "end",
        data: {},
      },
    ]
      .map((event) => {
        return `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
      })
      .join("");

    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body,
    });
  };

  await page.route("**/api/langgraph/runs/stream", handleRevisionStream);
  await page.route("**/api/langgraph/threads/*/runs/stream", handleRevisionStream);

  await page.goto("/workspace/chats/new");

  const emailInput = page.getByLabel("Email");
  if (await emailInput.isVisible()) {
    await emailInput.fill("e2e@example.com");
    await page.getByLabel("Password").fill("password123");
    await page.getByRole("button", { name: "Sign In" }).click();
  }

  const textarea = page.getByPlaceholder(/how can i assist you/i);
  await textarea.fill("Switch to plan B");
  await textarea.press("Enter");

  await expect(page.getByTestId("revision-timeline")).toBeVisible();
  await expect(page.getByTestId("revision-timeline")).toContainText("R1.0");
  await expect(page.getByTestId("active-revision-badge")).toContainText("R1.0");

  await textarea.fill("Switch again");
  await textarea.press("Enter");

  await expect(page.getByTestId("revision-timeline")).toContainText("R1.1");
  await expect(page.getByTestId("active-revision-badge")).toContainText("R1.1");
});