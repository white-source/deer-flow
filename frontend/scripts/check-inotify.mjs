#!/usr/bin/env node
/**
 * Pre-flight check for Linux inotify limits (Turbopack / Next dev).
 * Writes NDJSON to the Cursor debug log when DEBUG_LOG_PATH is set.
 */
import { readFileSync, appendFileSync, existsSync } from "node:fs";

const DEBUG_LOG =
  process.env.DEBUG_LOG_PATH ??
  "/home/SENSETIME/fengxiaohui/Documents/Code/deer-flow/.cursor/debug-40c205.log";

function readInt(path) {
  try {
    return parseInt(readFileSync(path, "utf8").trim(), 10);
  } catch {
    return null;
  }
}

const maxWatches = readInt("/proc/sys/fs/inotify/max_user_watches");
const maxInstances = readInt("/proc/sys/fs/inotify/max_user_instances");
const cookieParserExists = existsSync(
  new URL(
    "../node_modules/next/dist/server/api-utils/get-cookie-parser.js",
    import.meta.url,
  ),
);

const payload = {
  sessionId: "40c205",
  hypothesisId: "A",
  location: "scripts/check-inotify.mjs",
  message: "inotify preflight",
  data: {
    max_user_watches: maxWatches,
    max_user_instances: maxInstances,
    get_cookie_parser_exists: cookieParserExists,
    recommended_min_watches: 524288,
    watch_limit_likely_insufficient:
      maxWatches != null && maxWatches < 524288,
  },
  timestamp: Date.now(),
  runId: process.env.DEBUG_RUN_ID ?? "preflight",
};

// #region agent log
try {
  appendFileSync(DEBUG_LOG, `${JSON.stringify(payload)}\n`);
} catch {
  /* ignore */
}
// #endregion

const insufficient = payload.data.watch_limit_likely_insufficient;
console.log(
  `[inotify] max_user_watches=${maxWatches} max_user_instances=${maxInstances} get-cookie-parser=${cookieParserExists ? "present" : "MISSING"}`,
);
if (insufficient) {
  console.warn(
    "[inotify] Limit is below 524288 — Turbopack often fails with 'OS file watch limit reached' and false 'Module not found' errors.",
  );
  console.warn(
    "  Fix: sudo sysctl -w fs.inotify.max_user_watches=524288 fs.inotify.max_user_instances=512",
  );
  process.exit(1);
}
