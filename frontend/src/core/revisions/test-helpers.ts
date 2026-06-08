/**
 * Test helper for Playwright E2E tests.
 *
 * Exposes revision actions on window.__test_triggerRevisionAction
 * so Playwright tests can bypass LLM-based Talker intent recognition
 * and directly trigger the revision action hooks.
 *
 * Usage in Playwright tests:
 *   await page.evaluate(() => {
 *     window.__test_triggerRevisionAction?.({
 *       intent: "inject",
 *       revisionId: "rev-a",
 *       instruction: "不看8月，查9月",
 *       mode: "replace",
 *     });
 *   });
 */

export type RevisionIntent = "inject" | "cancel" | "resume";

export interface RevisionActionParams {
  intent: RevisionIntent;
  revisionId: string;
  instruction?: string;
  mode?: "replace" | "continue";
}

export type TriggerRevisionAction = (
  params: RevisionActionParams,
) => Promise<void>;

declare global {
  interface Window {
    __test_triggerRevisionAction?: TriggerRevisionAction;
  }
}

/**
 * Register the test trigger function on window.
 * Called during app initialization in E2E test mode
 * (NEXT_PUBLIC_E2E_TEST=true).
 */
export function registerTestRevisionTrigger(
  trigger: TriggerRevisionAction,
): void {
  if (typeof window !== "undefined") {
    window.__test_triggerRevisionAction = trigger;
  }
}
