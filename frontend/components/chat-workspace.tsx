"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Clapperboard,
  Download,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Plus,
  Settings2,
  SlidersHorizontal,
  Square,
  Grid2X2,
  Palette,
  Images,
  Sparkles,
  X,
} from "lucide-react";
import { signOut } from "firebase/auth";
import { firebaseAuth } from "../lib/firebase";
import { ApiError, call } from "../lib/api";
import { operationKey, useWorkspace } from "../lib/workspace";
import { useStudio } from "../lib/studio-store";
import type {
  Asset,
  ChatMessage,
  Conversation,
  ConversationState,
  MessageBlock,
  CreativePreferences,
} from "../lib/studio-types";
import { Brand } from "./brand";
import { PrivateMedia } from "./private-media";

const WorkspaceTools = dynamic(() =>
  import("./workspace-tools").then((m) => m.WorkspaceTools),
);
const ProductionPlan = dynamic(() =>
  import("./production-view").then((m) => m.ProductionPlan),
);
const ProductionView = dynamic(() =>
  import("./production-view").then((m) => m.ProductionView),
);
const TimelineCanvas = dynamic(
  () => import("./timeline-canvas").then((m) => m.TimelineCanvas),
  { loading: () => <p role="status">Opening timeline…</p> },
);
const InlineComposition = dynamic(() =>
  import("./preview").then((m) => m.CompositionPreview),
);
type Props = {
  conversations: Conversation[];
  historyError?: string;
  conversationId: string | null;
  onSelect: (id: string | null) => void;
  onCreate: (runId?: string) => Promise<string>;
  onOpenRun: (id: string) => void;
  onCreateBlank: () => Promise<void>;
  onOpenComposition: (id: string) => Promise<void>;
  hasMore: boolean;
  onMore: () => Promise<void>;
};
const activeStates = ["queued", "running", "waiting_for_jobs"];

export function ChatWorkspace({
  conversations,
  historyError,
  conversationId,
  onSelect,
  onCreate,
  onOpenRun,
  onCreateBlank,
  onOpenComposition,
  hasMore,
  onMore,
}: Props) {
  const w = useWorkspace();
  const s = useStudio();
  const [sidebar, setSidebar] = useState(false);
  const [settings, setSettings] = useState(false);
  const [agentOpen, setAgentOpen] = useState(true);
  const [tools, setTools] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<CreativePreferences>({
    vibe: null,
    motion: "real_time",
  });
  const [policy, setPolicy] = useState("product_launch");
  const [agentWidth, setAgentWidth] = useState(390);
  const [canvas, setCanvas] = useState(false);
  const [text, setText] = useState("");
  const [duration, setDuration] = useState(15);
  const [format, setFormat] = useState<"9:16" | "16:9">("9:16");
  const [locale, setLocale] = useState("en");
  const [cap, setCap] = useState("");
  const [attachments, setAttachments] = useState<Asset[]>([]);
  const [later, setLater] = useState<ChatMessage[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const input = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const historyPanel = useRef<HTMLElement>(null);
  const atBottom = useRef(true);
  const openButton = useRef<HTMLElement | null>(null);
  const toolsButton = useRef<HTMLElement | null>(null);
  function openTools(panel: string) {
    toolsButton.current = document.activeElement as HTMLElement;
    setTools(panel);
  }
  function closeTools() {
    setTools(null);
    requestAnimationFrame(() => toolsButton.current?.focus());
  }
  const [newMessages, setNewMessages] = useState(false);
  const sendKey = useRef<string | null>(null);
  const lastText = useRef("");
  const query = useQuery({
    queryKey: ["conversations", w.user.uid, w.projectId, conversationId],
    enabled: !!conversationId,
    queryFn: async () =>
      (await call(`${w.base}/conversations/${conversationId}?tail=true`))
        .data as ConversationState,
    retry: (count, e) =>
      !(e instanceof ApiError && e.status === 429) && count < 1,
    refetchInterval: (q) =>
      q.state.error instanceof ApiError && q.state.error.status === 429
        ? false
        : q.state.data?.operations?.some(
              (j) => j.status === "submission_unknown",
            ) ||
            q.state.data?.messages.some(
              (m) => m.status === "needs_reconciliation",
            )
          ? 15000
          : q.state.data?.messages.some((m) =>
                ["queued", "running"].includes(m.status || ""),
              ) ||
              q.state.data?.operations?.some(
                (j) =>
                  ![
                    "succeeded",
                    "failed",
                    "cancelled",
                    "submission_unknown",
                  ].includes(j.status),
              ) ||
              w.data?.jobs.some(
                (j) =>
                  ![
                    "succeeded",
                    "failed",
                    "cancelled",
                    "submission_unknown",
                  ].includes(j.status),
              )
            ? 2500
            : activeStates.includes(q.state.data?.run?.status || "")
              ? 5000
              : false,
  });
  useEffect(() => {
    setSidebar(false);
  }, []);
  useEffect(() => {
    if (!sidebar) return;
    const previous = document.activeElement as HTMLElement;
    historyPanel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, [sidebar]);

  useEffect(() => {
    setCanvas(false);
    setAgentOpen(true);
    setPreferences({ vibe: null, motion: "real_time" });
    setText("");
    setAttachments([]);
    setLater([]);
    setNext(undefined);
    atBottom.current = true;
    setNewMessages(false);
    sendKey.current = null;
  }, [conversationId]);
  const messages = [...(query.data?.messages || []), ...later]
    .filter((m, i, a) => a.findIndex((x) => x.id === m.id) === i)
    .sort((a, b) => a.sequence - b.sequence);
  const version =
    messages.map((m) => m.id + ":" + m.status).join("|") +
    query.data?.run?.version;
  useEffect(() => {
    if (atBottom.current) {
      scroll.current?.scrollTo({ top: scroll.current.scrollHeight });
    } else setNewMessages(true);
  }, [version]);
  useEffect(() => {
    const thread = scroll.current?.firstElementChild;
    if (!thread) return;
    const resize = new ResizeObserver(() => {
      if (atBottom.current && scroll.current)
        scroll.current.scrollTop = scroll.current.scrollHeight;
    });
    resize.observe(thread);
    return () => resize.disconnect();
  }, []);
  useEffect(() => {
    const story =
      messages
        .flatMap((m) => m.blocks)
        .filter(
          (b) =>
            b.kind === "storyboard" &&
            b.artifact_id === query.data?.conversation.storyboard_head,
        )
        .at(-1)?.storyboard || query.data?.production?.storyboard;
    if (story) {
      setDuration(story.duration_seconds);
      setFormat(story.aspect_ratio);
      setPreferences(
        story.creative_preferences || { vibe: null, motion: "real_time" },
      );
    }
  }, [query.data?.conversation.storyboard_head]);
  useEffect(() => {
    if (canvas) {
      const timer = setTimeout(
        () =>
          document
            .querySelector<HTMLButtonElement>('[aria-label="Back to preview"]')
            ?.focus(),
        100,
      );
      return () => clearTimeout(timer);
    }
  }, [canvas]);
  useEffect(() => {
    const head = query.data?.conversation.composition_head;
    if (head && head !== w.data?.project.composition_head) void w.refresh();
  }, [query.data?.conversation.composition_head]);
  const previousHead = useRef<string | null>(null);
  useEffect(() => {
    const head = query.data?.conversation.composition_head;
    if (head && !previousHead.current && window.innerWidth < 700)
      setAgentOpen(false);
    previousHead.current = head || null;
  }, [query.data?.conversation.composition_head]);
  const latestApproval = query.data?.run?.approval;
  const pending = [
    ...(latestApproval ? [latestApproval] : []),
    ...(w.data?.approvals || []),
  ].filter(
    (a, i, all) =>
      a.decision === "pending" &&
      a.conversation_id === conversationId &&
      all.findIndex((x) => x.id === a.id) === i &&
      (!a.run_id ||
        (a.run_id === query.data?.run?.run_id &&
          a.id === query.data?.run?.pending_approval_id)) &&
      (a.kind !== "preview" ||
        a.target_artifact_id === query.data?.conversation.composition_head),
  );
  const directionPending = messages.some((m) =>
    ["queued", "running", "needs_reconciliation"].includes(m.status || ""),
  );
  const generating =
    messages.some((m) => ["queued", "running"].includes(m.status || "")) ||
    activeStates.includes(query.data?.run?.status || "") ||
    !!query.data?.operations?.some(
      (j) =>
        !["succeeded", "failed", "cancelled", "submission_unknown"].includes(
          j.status,
        ),
    );
  async function refresh() {
    await Promise.all([w.refresh(), query.refetch()]);
  }
  async function send() {
    if (!text.trim() || w.busy) return;
    if (s.dirty) {
      w.setError(
        "Save or discard your timeline edits before asking the director to change this video.",
      );
      return;
    }
    if (!sendKey.current || lastText.current !== text) {
      sendKey.current = operationKey();
      lastText.current = text;
    }
    const key = sendKey.current;
    const submitted = text;
    await w.action(async () => {
      const id = conversationId || (await onCreate());
      await call(`${w.base}/conversations/${id}/messages`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: key,
          text: submitted,
          duration_seconds: duration,
          aspect_ratio: format,
          locale,
          policy,
          creative_preferences:
            JSON.stringify(preferences) !==
            JSON.stringify(
              query.data?.production?.storyboard?.creative_preferences || {
                vibe: null,
                motion: "real_time",
              },
            )
              ? preferences
              : undefined,
          workflow_mode: "bulk",
          reference_artifact_ids: attachments
            .filter((a) => a.type === "image")
            .map((a) => a.id)
            .slice(0, 3),
          spend_cap_micros: cap ? Math.round(Number(cap) * 1e6) : null,
        }),
      });
      setText("");
      setAttachments([]);
      sendKey.current = null;
      atBottom.current = true;
      await refresh();
    });
  }
  async function accept(approvalId: string, target: string) {
    await w.action(async () => {
      await call(`${w.base}/conversations/${conversationId}/actions`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: operationKey(),
          action: "approve",
          approval_id: approvalId,
          target_artifact_id: target,
        }),
      });
      const approval = pending.find((a) => a.id === approvalId);
      if (approval?.kind === "preview" && !approval.run_id)
        await w.submit("/renders", {
          composition_artifact_id: target,
          quality: "final",
        });
      await refresh();
    });
  }
  async function download(id: string) {
    const response = await call(`${w.base}/assets/${id}`);
    await w.download(response.data);
  }
  function openTimeline() {
    openButton.current = document.activeElement as HTMLElement;
    setCanvas(true);
  }
  function closeTimeline() {
    s.play(false);
    setCanvas(false);
    openButton.current?.focus();
  }
  function revise(scene?: string) {
    setAgentOpen(true);
    setText(scene ? `Change ${scene}: ` : "Change the storyboard: ");
    input.current?.focus();
  }
  const [leaveProjects, setLeaveProjects] = useState(false);
  async function goProjects() {
    if (s.dirty) {
      setLeaveProjects(true);
      return;
    }
    window.location.assign("/");
  }
  async function requestExport() {
    if (s.dirty) {
      await w.action(async () => {
        await w.save();
        await refresh();
        setCanvas(false);
        w.setNotice(
          "Your new revision is saved. Review it, then approve and export.",
        );
      });
      return;
    }
    const approval = pending.find((a) => a.kind === "preview");
    if (approval) {
      await accept(approval.id, approval.target_artifact_id);
      return;
    }
    await w.action(async () => {
      const current = w.head;
      if (!current) return;
      const review = await call(
        `${w.base}/compositions/${current}/review?conversation_id=${conversationId}`,
        {
          method: "POST",
          body: JSON.stringify({ idempotency_key: operationKey() }),
        },
      );
      if (review.data.decision === "approved") {
        await w.submit("/renders", {
          composition_artifact_id: current,
          quality: "final",
        });
        w.setNotice("Exporting your approved video…");
      } else if (review.data.decision !== "pending")
        throw new Error(
          "This version was rejected. Save a revision before exporting.",
        );
      else
        w.setNotice(
          "Review this exact version, then choose Approve and export.",
        );
      await refresh();
    });
  }
  const currentHead = query.data?.conversation.composition_head;
  const failed = query.data?.run?.status === "failed";
  const uncertain =
    query.data?.run?.status === "needs_reconciliation" ||
    query.data?.operations?.some((j) => j.status === "submission_unknown");
  if (
    (query.error instanceof ApiError &&
      [401, 403].includes(query.error.status)) ||
    (w.queryError instanceof ApiError &&
      [401, 403].includes(w.queryError.status))
  ) {
    return (
      <main className="chat-workspace">
        <section className="chat-main">
          <div className="chat-thread">
            <h2>This workspace is unavailable</h2>
            <p role="alert">
              Your access has changed. Sign in again or return to your projects.
            </p>
            <Link href="/">Back to projects</Link>
          </div>
        </section>
      </main>
    );
  }
  return (
    <main
      className={`chat-workspace unified-workspace ${conversationId ? "has-video" : "idea-screen"} ${agentOpen ? "" : "agent-collapsed"} ${canvas ? "canvas-open" : ""}`}
    >
      <header className="chat-header unified-header">
        <Link
          href="/"
          aria-label="VibeShorts home"
          onClick={(e) => {
            e.preventDefault();
            void goProjects();
          }}
        >
          <Brand compact />
        </Link>
        <button
          onClick={() => setSidebar((v) => !v)}
          aria-label={sidebar ? "Close projects" : "Open projects"}
          aria-expanded={sidebar}
        >
          Projects
        </button>
        <span className="workspace-breadcrumb">
          {w.data?.project.name || "Loading…"} /{" "}
          <strong>{query.data?.conversation.title || "New video"}</strong>
        </span>
        <span className="chat-header-spacer" />
        <span className="workspace-status" role="status">
          {query.error
            ? "Connection interrupted"
            : uncertain
              ? "Checking request"
              : failed
                ? "Needs attention"
                : generating
                  ? "Creating your video"
                  : s.dirty
                    ? "Unsaved changes"
                    : currentHead
                      ? "Ready to review"
                      : "Plan your video"}
        </span>
        {conversationId && (
          <button
            aria-label={agentOpen ? "Collapse agent" : "Open agent"}
            aria-expanded={agentOpen}
            onClick={() => setAgentOpen((v) => !v)}
          >
            {agentOpen ? (
              <PanelLeftClose size={18} />
            ) : (
              <PanelLeftOpen size={18} />
            )}
            <span>Agent</span>
          </button>
        )}
        <button
          className="chat-button primary"
          disabled={w.busy || generating || !currentHead}
          onClick={() => void requestExport()}
        >
          <Download size={15} />
          Export
        </button>
      </header>
      <nav className="workspace-rail" aria-label="Workspace navigation">
        <button title="New video" onClick={() => onSelect(null)}>
          <Plus size={21} />
          <span>New video</span>
        </button>
        <button
          title="Projects"
          aria-expanded={sidebar}
          onClick={() => setSidebar((v) => !v)}
        >
          <Grid2X2 size={20} />
          <span>Projects</span>
        </button>
        <button title="Style" onClick={() => openTools("style")}>
          <Palette size={20} />
          <span>Style</span>
        </button>
        <button title="Library" onClick={() => openTools("assets")}>
          <Images size={20} />
          <span>Library</span>
        </button>
        <span />
        <button title="Settings" onClick={() => openTools("brand")}>
          <Settings2 size={20} />
          <span>Settings</span>
        </button>
      </nav>
      {sidebar && (
        <aside
          ref={historyPanel}
          className="chat-sidebar"
          onKeyDown={(e) => {
            if (e.key === "Escape") setSidebar(false);
            if (e.key === "Tab") {
              const list = Array.from(
                historyPanel.current?.querySelectorAll<HTMLElement>(
                  "button:not(:disabled),a[href]",
                ) || [],
              );
              if (e.shiftKey && document.activeElement === list[0]) {
                e.preventDefault();
                list.at(-1)?.focus();
              } else if (
                !e.shiftKey &&
                document.activeElement === list.at(-1)
              ) {
                e.preventDefault();
                list[0]?.focus();
              }
            }
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Projects and videos"
        >
          <div className="chat-sidebar-brand">
            <Link
              href="/"
              aria-label="All projects"
              onClick={(e) => {
                e.preventDefault();
                void goProjects();
              }}
            >
              <Brand compact />
            </Link>
          </div>
          <button
            className="chat-new-video"
            onClick={() => {
              onSelect(null);
              setSidebar(false);
            }}
          >
            <Plus size={18} /> New video
          </button>
          <button className="chat-button" onClick={() => openTools("batch")}>
            Create multiple videos
          </button>
          <span className="chat-sidebar-label">Your videos</span>
          <nav>
            {conversations.map((c) => (
              <button
                key={c.id}
                className={c.id === conversationId ? "selected" : ""}
                onClick={() => {
                  onSelect(c.id);
                  setSidebar(false);
                }}
                title={c.title}
              >
                <Clapperboard size={15} />
                <span>{c.title}</span>
              </button>
            ))}
            {!conversations.length && (
              <p>Every idea gets its own conversation.</p>
            )}
            {hasMore && (
              <button onClick={() => void w.action(onMore)}>More videos</button>
            )}
          </nav>
          {historyError && <p role="alert">{historyError}</p>}
          <div className="chat-sidebar-footer">
            <button onClick={() => void goProjects()}>← All projects</button>
            <button onClick={() => void signOut(firebaseAuth())}>
              <LogOut size={15} /> Sign out
            </button>
          </div>
        </aside>
      )}
      <section
        className="chat-main"
        aria-label="Video agent"
        style={conversationId ? { width: agentWidth } : undefined}
      >
        {conversationId && (
          <header className="agent-heading">
            <Sparkles size={18} />
            <strong>Video agent</strong>
            <span>Plan · create · refine</span>
          </header>
        )}
        <div
          className="chat-scroll"
          ref={scroll}
          onScroll={() => {
            const node = scroll.current;
            if (node) {
              atBottom.current =
                node.scrollHeight - node.scrollTop - node.clientHeight < 100;
              if (atBottom.current) setNewMessages(false);
            }
          }}
        >
          <div className="chat-thread">
            {!messages.length && (
              <div className="chat-welcome">
                <span className="imagine-label">
                  <Sparkles size={18} /> 01 / IMAGINE
                </span>
                <h1>
                  What’s your <span>story?</span>
                </h1>
                <p>Start with a spark — a scene, a feeling, a wild idea.</p>
              </div>
            )}
            {conversationId && query.isPending && (
              <p role="status">Loading your conversation…</p>
            )}
            <ProductionPlan state={query.data} />
            {messages.map((message) => (
              <article
                className={`chat-message ${message.role}`}
                key={message.id}
              >
                <div className="chat-message-label">
                  {message.role === "assistant" ? (
                    <>
                      <span className="chat-avatar">
                        <Clapperboard size={15} />
                      </span>
                      Director
                    </>
                  ) : (
                    "You"
                  )}
                </div>
                <div className="chat-message-body">
                  <p>{message.text}</p>
                  {message.blocks
                    .filter((block) => {
                      const production = query.data?.production;
                      if (
                        block.kind === "storyboard" &&
                        block.artifact_id ===
                          query.data?.conversation.storyboard_head
                      )
                        return false;
                      if (
                        block.kind === "scene" &&
                        production?.scenes.some(
                          (scene) =>
                            scene.video.artifact_id === block.artifact_id,
                        )
                      )
                        return false;
                      if (
                        block.kind === "video" &&
                        block.artifact_id === production?.draft.artifact_id
                      )
                        return false;
                      if (
                        block.kind === "composition" &&
                        block.artifact_id === currentHead
                      )
                        return false;
                      return true;
                    })
                    .map((block, index) => (
                      <ChatBlock
                        key={`${message.id}-${index}`}
                        block={block}
                        projectId={w.projectId}
                        onDownload={(id) => void w.action(() => download(id))}
                        onTimeline={openTimeline}
                        onRevise={revise}
                        onRetry={
                          block.retryable &&
                          block.job_id &&
                          query.data?.operations?.some(
                            (job) =>
                              job.job_id === block.job_id &&
                              job.status === "failed" &&
                              !job.retried_by &&
                              [
                                "director_turn",
                                "edit",
                                "composition",
                                "render",
                              ].includes(job.kind),
                          )
                            ? () =>
                                void w.action(async () => {
                                  await call(
                                    `${w.base}/conversations/${conversationId}/actions`,
                                    {
                                      method: "POST",
                                      body: JSON.stringify({
                                        idempotency_key: operationKey(),
                                        action: "retry",
                                        job_id: block.job_id,
                                      }),
                                    },
                                  );
                                  await refresh();
                                })
                            : undefined
                        }
                        currentStoryboard={
                          query.data?.conversation.storyboard_head || null
                        }
                      />
                    ))}
                  {message.status === "queued" && (
                    <small>
                      Request queued
                      {generating
                        ? " · current generation will finish first"
                        : ""}
                    </small>
                  )}
                  {message.status === "running" && (
                    <small className="chat-thinking" role="status">
                      Thinking through your request…
                    </small>
                  )}
                  {message.status === "cancelled" && <small>Stopped</small>}
                </div>
              </article>
            ))}
            {(next === undefined ? query.data?.next_cursor : next) && (
              <button
                className="chat-button"
                onClick={() =>
                  void w.action(async () => {
                    const page = (
                      await call(
                        `${w.base}/conversations/${conversationId}?tail=true&cursor=${next || query.data?.next_cursor}`,
                      )
                    ).data as ConversationState;
                    setLater((v) => [...v, ...page.messages]);
                    setNext(page.next_cursor);
                  })
                }
              >
                Load earlier messages
              </button>
            )}
            {pending
              .filter((a) => a.kind !== "preview")
              .map((approval) => (
                <section
                  className="chat-review"
                  key={approval.id}
                  aria-label={`${approval.kind} approval`}
                >
                  <Check size={18} />
                  <div>
                    <strong>
                      {approval.kind === "storyboard"
                        ? "Ready to create your video?"
                        : approval.kind === "scene"
                          ? "How does this scene look?"
                          : "Ready to export this version?"}
                    </strong>
                    <p>
                      {approval.kind === "storyboard"
                        ? "Approve this storyboard to start production."
                        : approval.kind === "scene"
                          ? "Continue when you’re happy, or tell me what to change."
                          : "Approve the exact current video before final export."}
                    </p>
                    <div className="chat-card-actions">
                      <button
                        className="chat-button primary"
                        disabled={
                          w.busy ||
                          directionPending ||
                          s.dirty ||
                          (approval.kind === "preview" &&
                            approval.target_artifact_id !== currentHead)
                        }
                        onClick={() =>
                          void accept(approval.id, approval.target_artifact_id)
                        }
                      >
                        {approval.kind === "storyboard"
                          ? "Approve and create video"
                          : approval.kind === "scene"
                            ? "Continue"
                            : "Approve and export"}
                      </button>
                      <button
                        className="chat-button"
                        onClick={() => revise(approval.scene_id)}
                      >
                        Revise
                      </button>
                      {approval.kind === "preview" && (
                        <button className="chat-button" onClick={openTimeline}>
                          Edit
                        </button>
                      )}
                    </div>
                  </div>
                </section>
              ))}
            {generating && (
              <div className="chat-production-status" role="status">
                <span className="chat-pulse" />
                {query.data?.run?.workflow?.stage === "production"
                  ? "Creating your scenes…"
                  : query.data?.run?.workflow?.stage === "preview"
                    ? "Preparing your combined video…"
                    : "Working on your video…"}
              </div>
            )}
            {failed && (
              <div className="chat-review">
                <div>
                  <strong>A production step needs another try</strong>
                  <p>Your completed scenes are saved.</p>
                  <button
                    className="chat-button"
                    onClick={() =>
                      void w.action(async () => {
                        await call(
                          `${w.base}/conversations/${conversationId}/actions`,
                          {
                            method: "POST",
                            body: JSON.stringify({
                              idempotency_key: operationKey(),
                              action: "retry",
                            }),
                          },
                        );
                        await refresh();
                      })
                    }
                  >
                    Retry failed step
                  </button>
                </div>
              </div>
            )}
            {uncertain && (
              <p role="status">
                The provider may have accepted this request. We’re waiting for
                reconciliation before submitting it again.
              </p>
            )}
            {(w.error || query.error) && (
              <p className="chat-error" role="alert">
                {w.error || query.error?.message}
              </p>
            )}
            {w.notice && (
              <p className="chat-notice" role="status">
                {w.notice}
              </p>
            )}
          </div>
        </div>
        {newMessages && (
          <button
            className="chat-new-messages"
            onClick={() => {
              atBottom.current = true;
              setNewMessages(false);
              scroll.current?.scrollTo({ top: scroll.current.scrollHeight });
            }}
          >
            New messages <ChevronDown size={15} />
          </button>
        )}
        <footer className="chat-composer-region">
          <form
            className="chat-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            {attachments.length > 0 && (
              <div className="chat-attachments">
                {attachments.map((a) => (
                  <span key={a.id}>
                    {a.title}
                    <button
                      type="button"
                      aria-label={`Remove ${a.title}`}
                      onClick={() =>
                        setAttachments((v) => v.filter((x) => x.id !== a.id))
                      }
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <textarea
              ref={input}
              aria-label="Message your video director"
              value={text}
              maxLength={6000}
              rows={2}
              placeholder="Describe your video, or ask for a change…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            {!conversationId && (
              <span className="agent-auto">
                <Sparkles size={14} /> Your video director
              </span>
            )}
            {settings && (
              <div className="chat-settings">
                <label>
                  Length
                  <select
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                  >
                    {![6, 10, 15, 20, 30].includes(duration) && (
                      <option value={duration}>{duration} seconds</option>
                    )}
                    {[6, 10, 15, 20, 30].map((d) => (
                      <option key={d} value={d}>
                        {d} seconds
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Language
                  <select
                    value={locale}
                    onChange={(e) => setLocale(e.target.value)}
                  >
                    {[
                      ["en", "English"],
                      ["es", "Spanish"],
                      ["fr", "French"],
                      ["hi", "Hindi"],
                      ["de", "German"],
                      ["ja", "Japanese"],
                    ].map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Creative policy
                  <select
                    value={policy}
                    onChange={(e) => setPolicy(e.target.value)}
                  >
                    <option value="product_launch">Product launch</option>
                    <option value="explainer">Explainer</option>
                    <option value="social_ad">Social ad</option>
                  </select>
                </label>
                <label>
                  Allowance ($)
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={cap}
                    placeholder="Project budget"
                    onChange={(e) => setCap(e.target.value)}
                  />
                </label>
              </div>
            )}
            <div className="chat-composer-actions">
              <input
                type="file"
                hidden
                ref={upload}
                accept="image/png,image/jpeg,video/mp4,audio/wav,audio/mpeg,.woff2,.ttf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    void w.action(async () => {
                      const asset = await w.importAsset(file);
                      if (asset.type === "image")
                        setAttachments((v) => [...v, asset].slice(0, 3));
                      else
                        w.setNotice(
                          "Imported into your library. Open Library to add it to your cut.",
                        );
                    });
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                aria-label="Attach an asset"
                disabled={w.busy}
                onClick={() => upload.current?.click()}
              >
                <Paperclip size={19} />
              </button>
              <button
                type="button"
                aria-label="More options"
                aria-expanded={settings}
                onClick={() => setSettings((v) => !v)}
              >
                <Settings2 size={18} /> {!conversationId && "More options"}
              </button>
              <span>
                {duration}s · {format === "9:16" ? "Portrait" : "Landscape"}
              </span>
              <span className="chat-header-spacer" />
              {generating && (
                <button
                  type="button"
                  aria-label="Stop generation"
                  disabled={w.busy}
                  onClick={() =>
                    void w.action(async () => {
                      await call(
                        `${w.base}/conversations/${conversationId}/actions`,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            idempotency_key: operationKey(),
                            action: "cancel",
                          }),
                        },
                      );
                      await refresh();
                    })
                  }
                >
                  <Square size={16} />
                </button>
              )}
              <button
                type="submit"
                className="chat-send"
                aria-label="Send message"
                disabled={
                  w.busy ||
                  !text.trim() ||
                  (!!cap && (!Number.isFinite(Number(cap)) || Number(cap) <= 0))
                }
              >
                {!conversationId ? (
                  <>
                    Create storyboard <ArrowUp size={18} />
                  </>
                ) : (
                  <ArrowUp size={20} />
                )}
              </button>
            </div>
          </form>
          {!conversationId && (
            <>
              <CreativeControls
                preferences={preferences}
                onChange={setPreferences}
                format={format}
                onFormat={setFormat}
              />
              <div className="chat-starters">
                {[
                  "A perfume bottle on volcanic rock",
                  "A black hole, explained in 20 seconds",
                  "Only write a storyboard for a tiny robot",
                ].map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => {
                      setText(prompt);
                      input.current?.focus();
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </>
          )}
          <p className="chat-composer-hint">
            Review the plan first. We’ll create your video after approval.
            {w.data?.provider_route === "fixture" ? " · Fixture mode" : ""}
          </p>
        </footer>
      </section>
      {conversationId && (
        <>
          {agentOpen && (
            <div
              className="agent-resize"
              role="separator"
              tabIndex={0}
              aria-label="Resize agent"
              aria-orientation="vertical"
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft")
                  setAgentWidth((v) => Math.max(300, v - 30));
                if (e.key === "ArrowRight")
                  setAgentWidth((v) => Math.min(600, v + 30));
              }}
              onPointerDown={(e) => {
                const grip = e.currentTarget,
                  start = e.clientX,
                  width = agentWidth;
                grip.setPointerCapture(e.pointerId);
                const move = (event: PointerEvent) =>
                  setAgentWidth(
                    Math.max(300, Math.min(600, width + event.clientX - start)),
                  );
                const end = () => {
                  grip.removeEventListener("pointermove", move);
                  grip.removeEventListener("pointerup", end);
                  grip.removeEventListener("pointercancel", end);
                };
                grip.addEventListener("pointermove", move);
                grip.addEventListener("pointerup", end);
                grip.addEventListener("pointercancel", end);
              }}
            />
          )}
          <section
            className="video-workspace-content"
            aria-label="Video workspace"
          >
            {canvas ? (
              <TimelineCanvas onClose={closeTimeline} />
            ) : (
              <ProductionView
                key={conversationId}
                state={query.data}
                onEdit={openTimeline}
                onRevise={revise}
                onExport={() => void requestExport()}
                busy={w.busy || generating || directionPending}
                pendingPreview={pending.some((a) => a.kind === "preview")}
              />
            )}
          </section>
        </>
      )}
      {leaveProjects && (
        <StyleDrawer
          onClose={() => setLeaveProjects(false)}
          title="Unsaved timeline changes"
        >
          <p>Save your changes before returning to projects?</p>
          <div className="chat-card-actions">
            <button
              className="chat-button"
              onClick={() => setLeaveProjects(false)}
            >
              Cancel
            </button>
            <button
              className="chat-button"
              onClick={() => {
                s.reset();
                window.location.assign("/");
              }}
            >
              Discard
            </button>
            <button
              className="chat-button primary"
              disabled={w.busy}
              onClick={() =>
                void w.action(async () => {
                  await w.save();
                  window.location.assign("/");
                })
              }
            >
              Save
            </button>
          </div>
        </StyleDrawer>
      )}
      {tools === "style" && (
        <StyleDrawer onClose={closeTools}>
          <CreativeControls
            preferences={preferences}
            onChange={setPreferences}
            format={format}
            onFormat={setFormat}
          />
          <p>
            Existing scenes keep their current look until you approve a revised
            storyboard.
          </p>
          {conversationId && (
            <button
              className="chat-button primary"
              onClick={() => {
                setText(
                  `Change the storyboard style to ${preferences.vibe || "the current visual style"}, motion to ${preferences.motion === "slow_motion" ? "slow motion" : "real-time"}, and format to ${format}. Explain which scenes will change before generating.`,
                );
                setTools(null);
                setAgentOpen(true);
                input.current?.focus();
              }}
            >
              Review changes with the agent
            </button>
          )}
        </StyleDrawer>
      )}
      {tools && tools !== "style" && (
        <WorkspaceTools
          key={conversationId + tools}
          panel={tools}
          onClose={closeTools}
          onOpenRun={onOpenRun}
          onCreateBlank={onCreateBlank}
          onOpenComposition={onOpenComposition}
        />
      )}
    </main>
  );
}

function ChatBlock({
  block,
  projectId,
  onDownload,
  onTimeline,
  onRevise,
  onRetry,
  currentStoryboard,
}: {
  block: MessageBlock;
  projectId: string;
  onDownload: (id: string) => void;
  onTimeline: () => void;
  onRevise: (scene?: string) => void;
  onRetry?: () => void;
  currentStoryboard: string | null;
}) {
  if (block.kind === "error" && onRetry)
    return (
      <button className="chat-button" onClick={onRetry}>
        Retry this step
      </button>
    );
  if (block.kind === "storyboard" && block.storyboard)
    return (
      <section className="chat-storyboard-card">
        <header>
          <strong>Storyboard</strong>
          <span>
            {block.storyboard.duration_seconds}s ·{" "}
            {block.storyboard.scenes.length} scenes
            {currentStoryboard !== block.artifact_id
              ? " · Earlier version"
              : ""}
          </span>
        </header>
        {block.storyboard.scenes.map((scene, i) => (
          <article key={scene.id}>
            <span className="chat-scene-number">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <h3>{scene.objective}</h3>
              <p>{scene.visual_prompt}</p>
              {scene.exact_copy.length > 0 && (
                <blockquote>{scene.exact_copy.join(" · ")}</blockquote>
              )}
              <small>
                {scene.editorial_duration_seconds.toFixed(1)} seconds
              </small>
            </div>
          </article>
        ))}
        <div className="chat-card-actions">
          <button className="chat-button" onClick={() => onRevise()}>
            Revise storyboard
          </button>
        </div>
      </section>
    );
  if (block.kind === "attachment" && block.artifact_id)
    return (
      <PrivateMedia
        projectId={projectId}
        artifactId={block.artifact_id}
        image
        title="Reference image"
      />
    );
  if (["scene", "video"].includes(block.kind) && block.artifact_id)
    return (
      <section className="chat-media-card">
        <PrivateMedia
          projectId={projectId}
          artifactId={block.artifact_id}
          title={
            block.kind === "scene"
              ? `Preview ${block.scene_id}`
              : "Combined video preview"
          }
        />
        {block.copy?.length && (
          <p className="chat-scene-copy">
            On-screen copy: {block.copy.join(" · ")}
          </p>
        )}
        <div className="chat-card-actions">
          <button
            className="chat-button"
            onClick={() => onRevise(block.scene_id)}
          >
            Revise {block.kind === "scene" ? "scene" : "video"}
          </button>
          {block.kind === "video" && (
            <button className="chat-button" onClick={onTimeline}>
              <SlidersHorizontal size={14} /> Edit
            </button>
          )}
        </div>
      </section>
    );
  if (block.kind === "composition" && block.artifact_id)
    return (
      <section className="chat-media-card">
        <InlineComposition
          projectId={projectId}
          artifactId={block.artifact_id}
          independent
        />
        <button className="chat-button" onClick={onTimeline}>
          Edit
        </button>
      </section>
    );
  if (block.kind === "export" && block.artifact_id)
    return (
      <button
        className="chat-button primary"
        onClick={() => onDownload(block.artifact_id!)}
      >
        <Download size={16} /> Download video
      </button>
    );
  return null;
}

function CreativeControls({
  preferences,
  onChange,
  format,
  onFormat,
}: {
  preferences: CreativePreferences;
  onChange: (value: CreativePreferences) => void;
  format: "9:16" | "16:9";
  onFormat: (value: "9:16" | "16:9") => void;
}) {
  return (
    <div className="creative-controls">
      <div role="group" aria-label="Vibe">
        <span>Vibe</span>
        {(
          [
            ["cinematic", "Cinematic"],
            ["cartoon", "Cartoon"],
            ["collage", "Collage"],
            ["3d", "3D"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={preferences.vibe === id}
            onClick={() =>
              onChange({
                ...preferences,
                vibe: preferences.vibe === id ? null : id,
              })
            }
          >
            {label}
          </button>
        ))}
      </div>
      <div role="group" aria-label="Motion">
        <span>Motion</span>
        {(
          [
            ["real_time", "Real-time"],
            ["slow_motion", "Slow motion"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={preferences.motion === id}
            onClick={() => onChange({ ...preferences, motion: id })}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="group" aria-label="Format">
        <span>Format</span>
        {(["9:16", "16:9"] as const).map((id) => (
          <button
            key={id}
            type="button"
            aria-pressed={format === id}
            onClick={() => onFormat(id)}
          >
            {id}
          </button>
        ))}
      </div>
    </div>
  );
}
function StyleDrawer({
  children,
  onClose,
  title = "Style & motion",
}: {
  children: React.ReactNode;
  onClose: () => void;
  title?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div
      className="workspace-drawer-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={ref}
        className="workspace-tools"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            const list = Array.from(
              ref.current?.querySelectorAll<HTMLElement>(
                'button:not(:disabled),input,select,textarea,[tabindex="0"]',
              ) || [],
            ).filter((n) => n.getClientRects().length);
            if (e.shiftKey && document.activeElement === list[0]) {
              e.preventDefault();
              list.at(-1)?.focus();
            } else if (!e.shiftKey && document.activeElement === list.at(-1)) {
              e.preventDefault();
              list[0]?.focus();
            }
          }
        }}
      >
        <header>
          <h2>{title}</h2>
          <button aria-label="Close dialog" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
