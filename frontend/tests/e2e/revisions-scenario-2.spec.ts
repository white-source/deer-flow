/**
 * E2E test: Scenario 2 - 修改任务参数 (inject mode=replace)
 *
 * User asks "查8月话费", then changes to "不看8月，查9月".
 * Talker recognizes intent=inject, mode=replace.
 * Runtime forks new revision with independent checkpoint namespace.
 */

import { test, expect } from "@playwright/test";

test.describe("Scenario 2: 修改任务参数 (mode=replace)", () => {
  test("修改参数后创建新 revision 并展示结果", async ({ page }) => {
    await page.goto("/workspace/chats/thread-e2e-scenario-2");

    // Wait for revision timeline to render
    await expect(
      page.locator('[data-testid="revision-timeline"]'),
    ).toBeVisible({ timeout: 5000 });

    // When: simulate Talker recognizing intent="inject" with mode="replace"
    await page.evaluate(() => {
      window.__test_triggerRevisionAction?.({
        intent: "inject",
        revisionId: "rev-a",
        instruction: "不看8月，查9月话费",
        mode: "replace",
      });
    });

    // Then: new revision is active in timeline
    await expect(
      page.locator('[data-testid="active-revision-badge"]'),
    ).toContainText("Active", { timeout: 3000 });

    // Old revision shows superseded
    await expect(
      page.locator('[data-testid="revision-item-rev-a"]'),
    ).toContainText("superseded", { timeout: 3000 });
  });
});
