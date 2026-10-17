import { ApiError } from "./api";
import type { ConversationState } from "./studio-types";

const terminal = new Set(["succeeded", "failed", "cancelled", "submission_unknown"]);
export function conversationIsActive(data?: ConversationState) {
  return !!data && (data.has_pending_message || data.messages.some(m => ["queued", "running"].includes(m.status || "")) ||
    data.operations?.some(j => !terminal.has(j.status)) || ["queued", "running", "waiting_for_jobs"].includes(data.run?.status || ""));
}

export function progressKey(data?: ConversationState) {
  return JSON.stringify([data?.conversation, data?.run?.version, data?.approvals,
    data?.messages.map(m => [m.id, m.status]), data?.operations?.map(j => [j.job_id, j.status])]);
}

export function pollDelay(error: unknown, errorAt: number, active: boolean, unchanged: number) {
  if (error instanceof ApiError && [401, 403].includes(error.status)) return false;
  if (error instanceof ApiError && error.status === 429)
    return Math.max(1000, errorAt + (error.retryAfterMs || 60000) - Date.now());
  if (error) return active ? 60000 : false;
  return active ? unchanged >= 2 ? 60000 : 30000 : false;
}
