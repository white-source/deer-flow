/**
 * E2E test: Scenario 4 - 垫词后打断 (cancel + inject mode=continue)
 *
 * User asks "8块是什么", sees partial result "8元是增值业务",
 * then interrupts with "我没订过啊".
 * Talker recognizes intent=inject, mode=continue.
 * Runtime: cancel current run, fork new revision inheriting checkpoint namespace.
 */

import { test, expect } from "@playwright/test";

test.describe("Scenario 4: 垫词后打断 (mode=continue)", () => {
  test("流式输出中途注入后返回调整结果", async ({ page }) => {
    await page.goto("/workspace/chats/thread-e2e-scenario-4");

    // Given: partial streaming result visible
    await expect(
      page.locator('[data-testid="chat-messages"]'),
    ).toContainText("增值业务", { timeout: 10000 });

    // When: user injects with continue mode (补充信息)
    await page.evaluate(async () => {
      await window.__test_triggerRevisionAction?.({
        intent: "inject",
        revisionId: "rev-a",
        instruction: "我没订过啊，重点查凭证",
        mode: "continue",
      });
    });

    // Then: adjusted result focuses on 凭证 verification
    await expect(
      page.locator('[data-testid="chat-messages"]'),
    ).toContainText("凭证", { timeout: 10000 });

    // Active revision badge shows new revision
    await expect(
      page.locator('[data-testid="active-revision-badge"]'),
    ).toContainText("Active", { timeout: 3000 });
  });
});
