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
import { subscribeRunSummaries, throttle } from "./realtime";
import { useStudio } from "./studio-store";
import type { Asset, StudioState } from "./studio-types";

export const projectRoot = (id: string) =>
  `/v1/projects/${encodeURIComponent(id)}`;
export const operationKey = () => crypto.randomUUID();

function useWorkspaceState(
  projectId: string,
  user: User,
  conversationId: string | null,
) {
  const base = projectRoot(projectId);
  const client = useQueryClient();
  const s = useStudio();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [head, setHead] = useState<string | null>(null);
  const loaded = useRef<string | null>(null);
  const scope = conversationId
    ? `?conversation_id=${encodeURIComponent(conversationId)}`
    : "";
  const query = useQuery({
    queryKey: ["studio", user.uid, projectId, conversationId],
    queryFn: async () =>
      (await call(`${base}/studio${scope}`)).data as StudioState,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 429) && count < 1,
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.status === 429
        ? false
        : query.state.data?.jobs.some(
              (job) =>
                ![
                  "succeeded",
                  "failed",
                  "cancelled",
                  "submission_unknown",
                ].includes(job.status),
            )
          ? 15000
          : false,
  });
  useEffect(() => {
    // The first snapshot repeats the initial fetch, and a single job transition can
    // fire several snapshots, so skip the first and refetch at most once a second.
    let first = true;
    const refetch = throttle(() => {
      void client.invalidateQueries({
        queryKey: ["studio", user.uid, projectId, conversationId],
        exact: true,
      });
      void client.invalidateQueries({
        queryKey: ["conversations", user.uid, projectId],
      });
    }, 1000);
    const unsubscribe = subscribeRunSummaries(projectId, () => {
      if (first) first = false;
      else refetch();
    });
    return () => {
      refetch.cancel();
      unsubscribe();
    };
  }, [projectId, user.uid, client, conversationId]);
  useEffect(() => {
    loaded.current = null;
    setHead(null);
    s.reset();
    setError("");
    setNotice("");
  }, [projectId, user.uid, conversationId]);
  useEffect(() => () => useStudio.getState().reset(), [projectId, user.uid]);
  useEffect(() => {
    let active = true;
    const current = query.data?.project.composition_head;
    if (!current || current === loaded.current || s.dirty) return;
    void call(
      `${base}/compositions?artifact_id=${encodeURIComponent(current)}${conversationId ? `&conversation_id=${conversationId}` : ""}`,
    )
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
  }, [query.data?.project.composition_head, s.dirty, base, conversationId]);
  useEffect(() => {
    if (query.isError) {
      s.reset();
      setHead(null);
    }
  }, [query.isError]);

  async function refresh() {
    await Promise.all([
      query.refetch(),
      client.invalidateQueries({ queryKey: ["assets", user.uid, projectId] }),
      client.invalidateQueries({
        queryKey: ["conversations", user.uid, projectId],
      }),
    ]);
  }
  async function action(task: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await track(async () => {
        await task();
        await refresh();
      });
    } catch (e) {
      setError((e as Error).message);
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
    const submitted = JSON.stringify(s.timeline);
    const result = await submit("/compositions", {
      ...s.timeline,
      expected_head: head,
    });
    setNotice("Saving your revision…");
    for (let i = 0; i < 60; i++) {
      const job = await call(`${base}/jobs/${result.job_id}`);
      if (job.status === "succeeded") {
        const current = await call(
          `${base}/compositions?artifact_id=${job.artifact_ids[0]}`,
        );
        loaded.current = job.artifact_ids[0];
        setHead(job.artifact_ids[0]);
        const editing = useStudio.getState();
        const changedWhileSaving =
          JSON.stringify(editing.timeline) !== submitted;
        if (changedWhileSaving)
          editing.edit({
            ...editing.timeline,
            expected_head: job.artifact_ids[0],
          });
        else
          editing.load({
            ...current.data.manifest.timeline,
            expected_head: job.artifact_ids[0],
          });
        await call(
          `${base}/compositions/${job.artifact_ids[0]}/review${scope}`,
          {
            method: "POST",
            body: JSON.stringify({ idempotency_key: operationKey() }),
          },
        );
        setNotice(
          changedWhileSaving
            ? "Saved the submitted version. Your newer edits are still unsaved."
            : "Saved. Review the new preview before exporting.",
        );
        return;
      }
      if (["failed", "cancelled", "submission_unknown"].includes(job.status))
        throw new Error(job.error?.message || "Revision could not be saved.");
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(
      "The save is still processing. Keep this video open until it finishes.",
    );
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
    queryError: query.error,
    data: query.data,
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
