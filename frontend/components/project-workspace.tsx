"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { User } from "firebase/auth";
import { ApiError, call } from "../lib/api";
import { useStudio } from "../lib/studio-store";
import {
  operationKey,
  projectRoot,
  WorkspaceProvider,
  useWorkspace,
} from "../lib/workspace";
import { emptyTimeline } from "../lib/studio-types";
import type { Conversation } from "../lib/studio-types";
import { ChatWorkspace } from "./chat-workspace";
import { LoadingState } from "./loading-state";

export function ProjectWorkspace({
  projectId,
  user,
}: {
  projectId: string;
  user: User;
}) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [transition, setTransition] = useState<(() => void) | null>(null);
  const cancelTransition = useRef<(() => void) | null>(null);
  const [linkError, setLinkError] = useState("");
  const queryClient = useQueryClient();
  const { data, error, isPending } = useQuery({
    queryKey: ["conversations", user.uid, projectId, "list"],
    queryFn: async () =>
      (await call(`${projectRoot(projectId)}/conversations`)).data as {
        conversations: Conversation[];
        next_cursor: string | null;
      },

    retry: (count, e) =>
      !(e instanceof ApiError && e.status === 429) && count < 1,
  });
  const [extra, setExtra] = useState<Conversation[]>([]);
  const [cursor, setCursor] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    setExtra([]);
    setCursor(undefined);
    const search = new URLSearchParams(window.location.search);
    setConversationId(search.get("chat"));
    setReady(true);
  }, [projectId, user.uid]);
  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("mode");
    if (conversationId) url.searchParams.set("chat", conversationId);
    else url.searchParams.delete("chat");
    window.history.replaceState(null, "", url);
  }, [ready, conversationId, user.uid]);
  function select(id: string | null) {
    const apply = () => setConversationId(id);
    if (id !== conversationId && useStudio.getState().dirty)
      setTransition(() => apply);
    else apply();
  }
  async function canSwitch() {
    if (!useStudio.getState().dirty) return true;
    return new Promise<boolean>((resolve) => {
      cancelTransition.current = () => resolve(false);
      setTransition(() => () => resolve(true));
    });
  }
  async function create(
    runId?: string,
    workflowMode: "bulk" | "guided" = "bulk",
    title = "New video",
    compositionId?: string,
  ) {
    const response = await call(`${projectRoot(projectId)}/conversations`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: operationKey(),
        run_id: runId,
        composition_artifact_id: compositionId,
        workflow_mode: workflowMode,
        title,
      }),
    });
    select(response.data.id);
    await queryClient.invalidateQueries({
      queryKey: ["conversations", user.uid, projectId],
    });
    return response.data.id as string;
  }
  function continueRun(runId: string) {
    void (async () => {
      if (!(await canSwitch())) return;
      setLinkError("");
      try {
        await create(runId);
      } catch (e) {
        setLinkError((e as Error).message);
      }
    })();
  }
  if (!ready)
    return (
      <LoadingState
        className="workspace-loading centered"
        label="Opening your workspace…"
      />
    );
  const history = [...(data?.conversations || []), ...extra].filter(
    (c, i, a) => a.findIndex((x) => x.id === c.id) === i,
  );
  return (
    <WorkspaceProvider
      projectId={projectId}
      user={user}
      conversationId={conversationId}
    >
      {linkError && <p role="alert">{linkError}</p>}
      <ChatWorkspace
        conversations={history}
        historyLoading={isPending}
        historyError={error?.message}
        conversationId={conversationId}
        onSelect={select}
        onCreate={create}
        onOpenRun={continueRun}
        onCreateBlank={async () => {
          if (!(await canSwitch())) return;
          const id = await create(undefined, "bulk", "Untitled video");
          await call(`${projectRoot(projectId)}/compositions`, {
            method: "POST",
            body: JSON.stringify({
              project_id: projectId,
              conversation_id: id,
              idempotency_key: operationKey(),
              input: {
                ...emptyTimeline,
                title: "Untitled video",
                accent: "#87ceeb",
              },
            }),
          });
          await queryClient.invalidateQueries({
            queryKey: ["conversations", user.uid, projectId],
          });
        }}
        onOpenComposition={async (id) => {
          if (!(await canSwitch())) return;
          await create(undefined, "bulk", "Existing cut", id);
        }}
        onDelete={async (id) => {
          await call(`${projectRoot(projectId)}/conversations/${id}`, {
            method: "DELETE",
          });
          if (id === conversationId) {
            useStudio.getState().reset();
            setConversationId(null);
          }
          setExtra((v) => v.filter((c) => c.id !== id));
          queryClient.removeQueries({
            queryKey: ["conversations", user.uid, projectId, id],
          });
          await queryClient.invalidateQueries({
            queryKey: ["conversations", user.uid, projectId],
          });
        }}
        hasMore={!!(cursor === undefined ? data?.next_cursor : cursor)}
        onMore={async () => {
          const response = await call(
            `${projectRoot(projectId)}/conversations?cursor=${cursor || data?.next_cursor}`,
          );
          setExtra((v) => [...v, ...response.data.conversations]);
          setCursor(response.data.next_cursor);
        }}
      />
      {transition && (
        <UnsavedDialog
          waitingForChoice={!!cancelTransition.current}
          onCancel={() => {
            cancelTransition.current?.();
            cancelTransition.current = null;
            setTransition(null);
          }}
          onDiscard={() => {
            useStudio.getState().reset();
            transition();
            cancelTransition.current = null;
            setTransition(null);
          }}
          onSaved={() => {
            transition();
            cancelTransition.current = null;
            setTransition(null);
          }}
        />
      )}
    </WorkspaceProvider>
  );
}

function UnsavedDialog({
  onCancel,
  onDiscard,
  onSaved,
  waitingForChoice,
}: {
  onCancel: () => void;
  onDiscard: () => void;
  onSaved: () => void;
  waitingForChoice: boolean;
}) {
  const w = useWorkspace();
  const [saving, setSaving] = useState(false);
  const disabled = saving || (w.busy && !waitingForChoice);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div className="chat-dialog-backdrop">
      <div
        ref={ref}
        className="chat-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Unsaved timeline changes"
        onKeyDown={(e) => {
          if (e.key === "Escape" && !disabled) onCancel();
          if (e.key === "Tab") {
            const buttons =
              ref.current?.querySelectorAll<HTMLButtonElement>("button");
            if (buttons && buttons.length) {
              const first = buttons[0],
                last = buttons[buttons.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
              }
            }
          }
        }}
      >
        <h2>Save your timeline changes?</h2>
        <p>
          Save this revision before opening another video, or discard the local
          edits.
        </p>
        {w.error && <p role="alert">{w.error}</p>}
        <div>
          <button disabled={disabled} onClick={onCancel}>
            Cancel
          </button>
          <button disabled={disabled} onClick={onDiscard}>
            Discard
          </button>
          <button
            className="chat-button primary"
            disabled={disabled}
            onClick={async () => {
              setSaving(true);
              await w.action(async () => {
                await w.save();
                if (useStudio.getState().dirty)
                  throw new Error("Your latest edits still need saving.");
                onSaved();
              });
              setSaving(false);
            }}
          >
            Save revision
          </button>
        </div>
      </div>
    </div>
  );
}
