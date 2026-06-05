"use client";

import { BotIcon, PlusSquare } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import { InputBox } from "@/components/workspace/input-box";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import {
  type BackgroundRunItem,
  BackgroundRunList,
} from "@/components/workspace/revisions/background-run-list";
import {
  type RevisionTimelineItem,
  RevisionTimeline,
} from "@/components/workspace/revisions/revision-timeline";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import { useThreadStream, useThreadTokenUsage } from "@/core/threads/hooks";
import { threadTokenUsageToTokenUsage } from "@/core/threads/token-usage";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function toNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function toRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return undefined;
}

function toArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function parseRevisionTimeline(source: unknown): RevisionTimelineItem[] {
  return toArray(source)
    .map((item) => toRecord(item))
    .filter((item): item is Record<string, unknown> => item !== undefined)
    .map((item) => {
      const revisionId =
        toNonEmptyString(item.revision_id) ?? toNonEmptyString(item.revisionId);
      if (!revisionId) {
        return undefined;
      }
      return {
        revisionId,
        label: toNonEmptyString(item.label) ?? revisionId,
        status:
          toNonEmptyString(item.status) ??
          toNonEmptyString(item.execution_status) ??
          "unknown",
      };
    })
    .filter((item): item is RevisionTimelineItem => item !== undefined);
}

function parseBackgroundRuns(source: unknown): BackgroundRunItem[] {
  return toArray(source)
    .map((item) => toRecord(item))
    .filter((item): item is Record<string, unknown> => item !== undefined)
    .map((item) => {
      const runId =
        toNonEmptyString(item.root_run_id) ??
        toNonEmptyString(item.rootRunId) ??
        toNonEmptyString(item.run_id) ??
        toNonEmptyString(item.runId);
      if (!runId) {
        return undefined;
      }
      return {
        runId,
        label: toNonEmptyString(item.label) ?? runId,
        status: toNonEmptyString(item.status) ?? "unknown",
      };
    })
    .filter((item): item is BackgroundRunItem => item !== undefined);
}

export default function AgentChatPage() {
  const { t } = useI18n();
  const router = useRouter();

  const { agent_name } = useParams<{
    agent_name: string;
  }>();

  const { agent } = useAgent(agent_name);

  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  // `isNewThread` gates history/token-usage fetches until the backend creates
  // the thread. `isWelcomeMode` controls only the centered welcome layout, so
  // it can flip immediately on submit without triggering eager history loads.
  const [isWelcomeMode, setIsWelcomeMode] = useState(isNewThread);
  const [settings, setSettings] = useThreadSettings(threadId);
  const [localSettings, setLocalSettings] = useLocalSettings();
  const { tokenUsageEnabled } = useModels();
  const threadTokenUsage = useThreadTokenUsage(
    isNewThread || isMock ? undefined : threadId,
    { enabled: tokenUsageEnabled && !isMock },
  );
  const backendTokenUsage = threadTokenUsageToTokenUsage(threadTokenUsage.data);

  const { showNotification } = useNotification();

  useEffect(() => {
    setIsWelcomeMode(isNewThread);
  }, [isNewThread]);

  const {
    thread,
    pendingUsageMessages,
    sendMessage,
    isUploading,
    queuedRunCount,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: { ...settings.context, agent_name: agent_name },
    isMock,
    onSend: () => {
      setIsWelcomeMode(false);
    },
    onStart: (createdThreadId) => {
      setThreadId(createdThreadId);
      setIsNewThread(false);
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(
        null,
        "",
        `/workspace/agents/${agent_name}/chats/${createdThreadId}`,
      );
    },
    onFinish: (state) => {
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages[state.messages.length - 1];
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            body =
              textContent.length > 200
                ? textContent.substring(0, 200) + "..."
                : textContent;
          }
        }
        showNotification(state.title, { body });
      }
    },
  });

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      const sendPromise = sendMessage(threadId, message, { agent_name });
      if (message.files.length > 0) {
        return sendPromise;
      }
      void sendPromise;
    },
    [sendMessage, threadId, agent_name],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const hasTodos = (thread.values.todos?.length ?? 0) > 0;
  const latestMessageAdditionalKwargs = useMemo(() => {
    const messages = thread.messages;
    for (let i = messages.length - 1; i >= 0; i--) {
      const message = messages[i];
      const additionalKwargs = toRecord(
        (message as { additional_kwargs?: unknown }).additional_kwargs,
      );
      if (additionalKwargs) {
        return additionalKwargs;
      }
    }
    return undefined;
  }, [thread.messages]);
  const revisionTimeline = useMemo(() => {
    const fromValues = parseRevisionTimeline(
      thread.values.revisions ?? thread.values.revision_timeline,
    );
    if (fromValues.length > 0) {
      return fromValues;
    }
    return parseRevisionTimeline(
      latestMessageAdditionalKwargs?.revisions ??
        latestMessageAdditionalKwargs?.revision_timeline,
    );
  }, [latestMessageAdditionalKwargs, thread.values]);
  const backgroundRuns = useMemo(() => {
    const fromValues = parseBackgroundRuns(
      thread.values.background_runs ?? thread.values.backgroundRuns,
    );
    if (fromValues.length > 0) {
      return fromValues;
    }
    return parseBackgroundRuns(
      latestMessageAdditionalKwargs?.background_runs ??
        latestMessageAdditionalKwargs?.backgroundRuns,
    );
  }, [latestMessageAdditionalKwargs, thread.values]);
  const activeRevisionId = useMemo(
    () =>
      toNonEmptyString(thread.values.active_revision_id) ??
      toNonEmptyString(thread.values.activeRevisionId) ??
      toNonEmptyString(latestMessageAdditionalKwargs?.active_revision_id) ??
      toNonEmptyString(latestMessageAdditionalKwargs?.activeRevisionId),
    [latestMessageAdditionalKwargs, thread.values],
  );

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ChatBox threadId={threadId}>
        <div className="relative flex size-full min-h-0 justify-between">
          <header
            className={cn(
              "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center gap-2 px-4",
              isWelcomeMode
                ? "bg-background/0 backdrop-blur-none"
                : "bg-background/80 shadow-xs backdrop-blur",
            )}
          >
            {/* Agent badge */}
            <div className="flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1">
              <BotIcon className="text-primary h-3.5 w-3.5" />
              <span className="text-xs font-medium">
                {agent?.name ?? agent_name}
              </span>
            </div>

            <div className="flex w-full items-center text-sm font-medium">
              <ThreadTitle threadId={threadId} thread={thread} />
            </div>
            <div className="mr-4 flex items-center">
              <Tooltip content={t.agents.newChat}>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    router.push(`/workspace/agents/${agent_name}/chats/new`);
                  }}
                >
                  <PlusSquare /> {t.agents.newChat}
                </Button>
              </Tooltip>
              <TokenUsageIndicator
                threadId={isNewThread ? undefined : threadId}
                backendUsage={backendTokenUsage}
                enabled={tokenUsageEnabled}
                messages={thread.messages}
                pendingMessages={pendingUsageMessages}
                preferences={localSettings.tokenUsage}
                onPreferencesChange={(preferences) =>
                  setLocalSettings("tokenUsage", preferences)
                }
              />
              <ExportTrigger threadId={threadId} />
              <ArtifactTrigger />
            </div>
          </header>

          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex min-h-0 flex-1 justify-center">
              <MessageList
                className={cn("size-full", !isWelcomeMode && "pt-10")}
                threadId={threadId}
                thread={thread}
                paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                hasMoreHistory={hasMoreHistory}
                loadMoreHistory={loadMoreHistory}
                isHistoryLoading={isHistoryLoading}
                tokenUsageInlineMode={tokenUsageInlineMode}
              />
            </div>

            <div
              className={cn(
                "right-0 bottom-0 left-0 z-30 flex justify-center px-4",
                isWelcomeMode ? "absolute" : "relative shrink-0 pb-4",
              )}
            >
              <div
                className={cn(
                  "relative w-full",
                  isWelcomeMode && "-translate-y-[calc(50vh-96px)]",
                  isWelcomeMode
                    ? "max-w-(--container-width-sm)"
                    : "max-w-(--container-width-md)",
                )}
              >
                {hasTodos && (
                  <div
                    className={cn(
                      "right-0 left-0 z-0",
                      isWelcomeMode ? "absolute -top-4" : "relative",
                    )}
                  >
                    <div
                      className={cn(
                        "right-0 bottom-0 left-0",
                        isWelcomeMode ? "absolute" : "relative",
                      )}
                    >
                      <TodoList
                        className="bg-background/5"
                        todos={thread.values.todos ?? []}
                        hidden={false}
                      />
                    </div>
                  </div>
                )}

                {queuedRunCount > 0 ? (
                  <p className="text-muted-foreground mb-2 text-center text-sm">
                    {queuedRunCount} message{queuedRunCount === 1 ? "" : "s"}{" "}
                    queued
                  </p>
                ) : null}

                <InputBox
                  className={cn(
                    "bg-background/5 w-full",
                    isWelcomeMode && "-translate-y-4",
                  )}
                  isWelcomeMode={isWelcomeMode}
                  threadId={threadId}
                  autoFocus={isWelcomeMode}
                  status={
                    thread.error
                      ? "error"
                      : thread.isLoading
                        ? "streaming"
                        : "ready"
                  }
                  context={settings.context}
                  extraHeader={
                    isWelcomeMode && (
                      <AgentWelcome agent={agent} agentName={agent_name} />
                    )
                  }
                  disabled={
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                    isUploading
                  }
                  onContextChange={(context) => setSettings("context", context)}
                  onSubmit={handleSubmit}
                  onStop={handleStop}
                />
                {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                  <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                    {t.common.notAvailableInDemoMode}
                  </div>
                )}
              </div>
            </div>
          </main>
          <aside className="border-border/60 bg-background/40 hidden w-72 shrink-0 border-l p-3 lg:flex lg:flex-col lg:gap-4">
            <RevisionTimeline
              revisions={revisionTimeline}
              activeRevisionId={activeRevisionId}
            />
            <BackgroundRunList runs={backgroundRuns} />
          </aside>
        </div>
      </ChatBox>
    </ThreadContext.Provider>
  );
}
