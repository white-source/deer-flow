/**
 * E2E test: Scenario 3 - 停止任务 (cancel → revision cancelled)
 *
 * User asks "流量余额", then says "算了不查了".
 * Talker recognizes intent=cancel.
 * Runtime cancels run, which triggers revision → cancelled transition.
 */

import { test, expect } from "@playwright/test";

test.describe("Scenario 3: 停止任务 (cancel → revision cancelled)", () => {
  test("取消任务后 revision 显示 cancelled 并展示确认消息", async ({ page }) => {
    await page.goto("/workspace/chats/thread-e2e-scenario-3");

    // When: cancel via test helper
    await page.evaluate(() => {
      window.__test_triggerRevisionAction?.({
        intent: "cancel",
        revisionId: "rev-a",
      });
    });

    // Then: revision shows cancelled in timeline
    await expect(
      page.locator('[data-testid="revision-item-rev-a"]'),
    ).toContainText("cancelled", { timeout: 3000 });

    // Confirmation message appears
    await expect(
      page.locator('[data-testid="chat-messages"]'),
    ).toContainText("好的", { timeout: 5000 });

    // Input re-enabled after cancel
    await expect(
      page.locator('[data-testid="chat-input"]'),
    ).toBeEnabled({ timeout: 3000 });
  });
});
