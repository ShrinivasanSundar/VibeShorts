"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { User } from "firebase/auth";
import { track } from "./loading";
import { ApiError, call, request } from "./api";
import { clearMediaCache } from "./media-cache";
import { conversationIsActive, pollDelay, progressKey } from "./polling";
import { subscribeConversation, subscribeRunActivity, throttle, type RunActivity } from "./realtime";
import { useStudio, useEditor } from "./studio-store";
import type { Asset, ConversationState, ProductionStep, StudioState } from "./studio-types";

export const projectRoot = (id: string) =>
  `/v1/projects/${encodeURIComponent(id)}`;
export const operationKey = () => crypto.randomUUID();
type PendingSave = { jobId: string; submitted: string; started: number };
function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) cancel();
  });
}

// A listener reports one job's new step: show it wherever the cached state lists that job,
// without an API call. Finished steps change the conversation document, which refetches.
function patchStep(state: ConversationState, activity: RunActivity): ConversationState {
  const step = (s: ProductionStep) =>
    s.job_id === activity.job_id ? { ...s, status: activity.status, updated_at: activity.updated_at } : s;
  const p = state.production;
  return {
    ...state,
    operations: state.operations?.map(j => (j.job_id === activity.job_id ? { ...j, status: activity.status } : j)),
    production: p && {
      ...p,
      scenes: p.scenes.map(s => ({ ...s, frame: step(s.frame), video: step(s.video), generation: step(s.generation) })),
      music: step(p.music),
      music_generation: step(p.music_generation),
      composition: step(p.composition),
      draft: step(p.draft),
      export: step(p.export),
    },
  };
}

function useWorkspaceState(
  projectId: string,
  user: User,
  conversationId: string | null,
) {
  const base = projectRoot(projectId);
  const client = useQueryClient();
  const s = useEditor();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [accessError, setAccessError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState("");
  const [head, setHead] = useState<string | null>(null);
  const loaded = useRef<string | null>(null);
  const scope = conversationId
    ? `?conversation_id=${encodeURIComponent(conversationId)}`
    : "";
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const progress = useRef({ key: "", unchanged: 0 });
  const saveObserver = useRef<AbortController | null>(null);
  const pendingSaveKey = ["pending-save", user.uid, projectId, conversationId];
  const query = useQuery({
    queryKey: ["workspace", user.uid, projectId, conversationId],
    enabled: !accessError,
    queryFn: async ({ signal }) => (await call(`${base}/studio${scope}${scope ? "&" : "?"}include_history=false&include_assets=false`, { signal })).data as StudioState,
  });
  const resources = useQuery({
    queryKey: ["studio", user.uid, projectId, conversationId],
    queryFn: async ({ signal }) => (await call(`${base}/studio${scope}`, { signal })).data as StudioState,
    enabled: resourcesOpen && !accessError,
  });
  const conversationKey = ["conversation", user.uid, projectId, conversationId];
  // True while the Firestore listeners below are connected; polling is then only a safety net.
  const [live, setLive] = useState(false);
  const conversationQuery = useQuery({
    queryKey: conversationKey,
    enabled: !!conversationId && !accessError,
    queryFn: async ({ signal }) => {
      // After the first load, fetch only messages written since the revision already held.
      const previous = client.getQueryData<ConversationState>(conversationKey);
      const since = previous?.revision !== undefined ? `&since=${previous.revision}` : "";
      let data = (await call(`${base}/conversations/${conversationId}?tail=true${since}`, { signal })).data as ConversationState;
      if (data.incremental && previous) {
        const merged = new Map(previous.messages.map(m => [m.id, m]));
        for (const message of data.messages) merged.set(message.id, message);
        data = { ...data, messages: [...merged.values()].sort((a, b) => a.sequence - b.sequence), next_cursor: previous.next_cursor };
      }
      const key = progressKey(data);
      progress.current = { key, unchanged: key === progress.current.key ? progress.current.unchanged + 1 : 0 };
      return data;
    },
    refetchInterval: q => {
      if (saving) return false;
      const delay = pollDelay(q.state.error, q.state.errorUpdatedAt, conversationIsActive(q.state.data), progress.current.unchanged);
      return live && delay !== false ? Math.max(delay, 120000) : delay;
    },
  });
  const activeRunId = conversationQuery.data?.run?.run_id;
  useEffect(() => {
    setLive(false);
    if (!conversationId || accessError) return;
    // Two single-document listeners, one read per change: the conversation document changes when
    // messages, heads or the run's state change; the run's activity document carries each job step.
    const refetch = throttle(() => void client.invalidateQueries({ queryKey: conversationKey, exact: true }), 2000);
    const unsubscribeChat = subscribeConversation(projectId, conversationId, refetch, setLive);
    const unsubscribeRun = activeRunId
      ? subscribeRunActivity(projectId, activeRunId, activity =>
          client.setQueryData<ConversationState>(conversationKey, current => current && patchStep(current, activity)))
      : () => {};
    return () => {
      refetch.cancel();
      unsubscribeChat();
      unsubscribeRun();
    };
  }, [projectId, user.uid, conversationId, activeRunId, accessError, client]);
  const data = query.data && !accessError ? {
    ...query.data,
    assets: resources.data?.assets || query.data.assets,
    runs: resources.data?.runs || query.data.runs,
    jobs: resources.data?.jobs || query.data.jobs,
    events: resources.data?.events || query.data.events,
    approvals: conversationQuery.data?.approvals || resources.data?.approvals || query.data.approvals,
    project: { ...query.data.project, composition_head: conversationQuery.data?.conversation.composition_head ?? query.data.project.composition_head },
  } : undefined;
  useEffect(() => {
    loaded.current = null;
    progress.current = { key: "", unchanged: 0 };
    setResourcesOpen(false);
    setHead(null);
    s.reset();
    setError("");
    setAccessError(null);
    setNotice("");
  }, [projectId, user.uid, conversationId]);
  useEffect(() => {
    const pending = client.getQueryData<PendingSave>(pendingSaveKey);
    if (pending) void action(() => observeSave(pending));
    return () => saveObserver.current?.abort();
  }, [projectId, user.uid, conversationId]);
  useEffect(() => () => useStudio.getState().reset(), [projectId, user.uid]);
  useEffect(() => {
    let active = true;
    const current = data?.project.composition_head;
    if (!current || current === loaded.current || s.dirty) return;
    void client.fetchQuery({
      queryKey: ["composition", user.uid, projectId, current], staleTime: Infinity,
      queryFn: ({ signal }) => call(`${base}/compositions?artifact_id=${encodeURIComponent(current)}${conversationId ? `&conversation_id=${conversationId}` : ""}`, { signal }),
    })
      .then((response) => {
        if (active) {
          loaded.current = current;
          setHead(current);
          s.load({
            ...response.data.manifest.timeline,
            expected_head: current,
          });
        }
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [data?.project.composition_head, s.dirty, base, conversationId, client, user.uid, projectId]);
  useEffect(() => {
    if ([query.error, conversationQuery.error, resources.error].some(e => e instanceof ApiError && [401, 403].includes(e.status))) {
      s.reset();
      setHead(null);
      clearMediaCache();
      const denied = [query.error, conversationQuery.error, resources.error].find(e => e instanceof ApiError && [401,403].includes(e.status)) as ApiError;
      setAccessError(denied);
      client.removeQueries({ queryKey: ["composition", user.uid, projectId] });
    }
  }, [query.error, conversationQuery.error, resources.error, client, user.uid, projectId]);

  const completed = conversationQuery.data?.operations?.filter(j => ["succeeded", "failed", "cancelled"].includes(j.status)).map(j => j.job_id).sort().join("|");
  const lastCompleted = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (lastCompleted.current !== undefined && completed !== lastCompleted.current) {
      void client.invalidateQueries({ queryKey: ["workspace", user.uid, projectId] });
      void client.invalidateQueries({ queryKey: ["studio", user.uid, projectId] });
    }
    lastCompleted.current = completed;
  }, [completed, user.uid, projectId, client]);
  async function refresh(includeResources = true) {
    await Promise.all([
      conversationId ? conversationQuery.refetch() : query.refetch(),
      includeResources && client.invalidateQueries({ queryKey: ["workspace", user.uid, projectId] }),
      includeResources && client.invalidateQueries({ queryKey: ["studio", user.uid, projectId] }),
      client.invalidateQueries({ queryKey: ["assets", user.uid, projectId] }),
      client.invalidateQueries({
        queryKey: ["conversations", user.uid, projectId],
      }),
    ]);
  }
  async function action(task: () => Promise<unknown>, includeResources = false) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await track(async () => {
        await task();
        await refresh(includeResources);
      });
    } catch (e) {
      if (e instanceof ApiError && [401,403].includes(e.status)) {
        setAccessError(e); clearMediaCache(); s.reset(); setHead(null);
      }
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function submit(path: string, input: unknown, key = operationKey()) {
    return call(base + path, {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        conversation_id: conversationId,
        idempotency_key: key,
        input,
      }),
    });
  }
  async function save() {
    const existing = client.getQueryData<PendingSave>(pendingSaveKey);
    if (existing) return observeSave(existing);
    const timeline = useStudio.getState().timeline;
    const result = await submit("/compositions", { ...timeline, expected_head: head });
    const pending = { jobId: result.job_id, submitted: JSON.stringify(timeline), started: Date.now() };
    client.setQueryDefaults(pendingSaveKey, { gcTime: Infinity });
    client.setQueryData(pendingSaveKey, pending);
    return observeSave(pending);
  }
  async function observeSave(pending: PendingSave) {
    saveObserver.current?.abort();
    const observer = new AbortController();
    saveObserver.current = observer;
    const signal = observer.signal;
    setNotice("Saving your revision…"); setSaving(true);
    const delays = [2000, 5000, 10000, 20000, 30000];
    let retryDelay = 0;
    try {
      for (let i = 0; ; i++) {
        await wait(Math.max(retryDelay, delays[Math.min(i, delays.length - 1)]), signal);
        retryDelay = 0;
        if (document.hidden || !navigator.onLine) continue;
        if (Date.now() - pending.started > 60000) setNotice("Your save is still processing. Your edits are safe while we wait.");
        let job;
        try { job = await call(`${base}/jobs/${pending.jobId}`, { signal }); }
        catch (error) {
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) throw error;
          if (signal.aborted) throw error;
          retryDelay = error instanceof ApiError ? error.retryAfterMs || 60000 : 60000;
          setNotice("Waiting to reconnect. Your save is still processing.");
          continue;
        }
        if (["failed", "cancelled", "submission_unknown"].includes(job.status)) {
          client.removeQueries({ queryKey: pendingSaveKey, exact: true });
          throw new Error(job.error?.message || "Revision could not be saved.");
        }
        if (job.status !== "succeeded") continue;
        const artifactId = job.artifact_ids[0];
        const current = await client.fetchQuery({ queryKey: ["composition", user.uid, projectId, artifactId], staleTime: Infinity,
          queryFn: () => call(`${base}/compositions?artifact_id=${artifactId}`, { signal }) });
        signal.throwIfAborted();
        loaded.current = artifactId; setHead(artifactId);
        const editing = useStudio.getState();
        const changedWhileSaving = editing.dirty && JSON.stringify(editing.timeline) !== pending.submitted;
        if (changedWhileSaving) editing.edit({ ...editing.timeline, expected_head: artifactId });
        else editing.load({ ...current.data.manifest.timeline, expected_head: artifactId });
        client.removeQueries({ queryKey: pendingSaveKey, exact: true });
        setNotice(changedWhileSaving ? "Saved the submitted version. Your newer edits are still unsaved." : "Saved. Review the new preview before exporting.");
        return;
      }
    } finally {
      if (saveObserver.current === observer) setSaving(false);
    }
  }
  async function importAsset(file: File): Promise<Asset> {
    const mime =
      file.type ||
      (
        {
          woff2: "font/woff2",
          ttf: "font/ttf",
          wav: "audio/wav",
          mp3: "audio/mpeg",
          mp4: "video/mp4",
        } as Record<string, string>
      )[file.name.split(".").at(-1) || ""];
    const response = await call(`${base}/uploads`, {
      method: "POST",
      body: JSON.stringify({
        title: file.name,
        mime_type: mime,
        size_bytes: file.size,
        idempotency_key: operationKey(),
      }),
    });
    const upload = response.data;
    const headers: Record<string, string> = {
      "Content-Type": upload.headers["Content-Type"],
    };
    if (upload.requires_authorization)
      await request(`${base}/uploads/${upload.upload_id}/content`, {
        method: "PUT",
        headers,
        body: file,
      });
    else {
      headers["x-goog-if-generation-match"] = "0";
      const uploaded = await fetch(upload.upload_url, {
        method: "PUT",
        headers,
        body: file,
      });
      if (!uploaded.ok) throw new Error("Upload failed.");
    }
    const completed = await call(`${base}/uploads/complete`, {
      method: "POST",
      body: JSON.stringify({
        upload_id: upload.upload_id,
        idempotency_key: operationKey(),
      }),
    });
    setNotice("Asset verified and imported.");
    return completed.data;
  }
  async function download(asset: Asset) {
    const url = URL.createObjectURL(
      await (await request(`${base}/assets/${asset.id}/content`)).blob(),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${asset.title.replace(/[^a-z0-9_-]/gi, "-")}.${asset.media.mime_type === "video/mp4" ? "mp4" : asset.type === "composition" ? "zip" : asset.type === "audio" ? "wav" : "png"}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function decision(id: string, target: string, approved: boolean) {
    await call(`${base}/approvals/${id}`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: operationKey(),
        target_artifact_id: target,
        approved,
      }),
    });
    setNotice(
      approved ? "Approved. Your video will continue." : "Paused for revision.",
    );
  }
  return {
    ...query,
    queryError: accessError || query.error || resources.error,
    data,
    conversationQuery: accessError ? { ...conversationQuery, data: undefined, error: accessError } : conversationQuery,
    loadResources: () => { setResourcesOpen(true); return () => setResourcesOpen(false); },
    projectId,
    user,
    conversationId,
    base,
    busy,
    error,
    notice,
    head,
    setHead,
    setError,
    setNotice,
    action,
    submit,
    save,
    importAsset,
    download,
    decision,
    refresh,
  };
}

type Workspace = ReturnType<typeof useWorkspaceState>;
const Context = createContext<Workspace | null>(null);
export function WorkspaceProvider({
  projectId,
  user,
  conversationId,
  children,
}: {
  projectId: string;
  user: User;
  conversationId: string | null;
  children: ReactNode;
}) {
  const value = useWorkspaceState(projectId, user, conversationId);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error("WorkspaceProvider is required.");
  return value;
}
