"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type { CreativeBrief, EditPlan, JobStatus, Conversation } from "@/lib/types";
import {
  createConversation,
  sendConversationMessage,
  subscribeToConversationStream,
  updateConversationPlan,
  triggerConversationRender,
  triggerGeneration,
  subscribeToJobStream,
  getVideoUrl,
  sendChatMessage,
  renderCustomPlan,
} from "@/lib/api";
import { MessageItem } from "@/components/chat/ChatContainer";

// ─── Default creative brief ────────────────────────────────────────
const DEFAULT_BRIEF: CreativeBrief = {
  product_name: "AeroGlow Pro",
  target_audience: "Gen-Z tech creators & mobile videographers",
  tone: "energetic",
  duration_seconds: 30,
  key_value_props: ["4K AI Sensor", "Ultra-lightweight gimbal", "30h battery life"],
  call_to_action: "Tap the link in bio to claim yours!",
};

// ─── Simulated pipeline (fallback when backend is offline) ─────────
function buildSimulatedPlan(projectId: string, brief: CreativeBrief): EditPlan {
  return {
    plan_id: `plan_${projectId}_v1`,
    project_id: projectId,
    revision: 1,
    total_target_duration: brief.duration_seconds,
    cuts: [
      {
        cut_index: 1,
        shot_id: "shot_hook_speaker_01",
        source_file_uri: "media/intro.mp4",
        in_point_sec: 0.0,
        out_point_sec: 2.8,
        text_overlay: "Wait until you see this! ⚡",
      },
      {
        cut_index: 2,
        shot_id: "shot_broll_macro_sensor",
        source_file_uri: "media/broll_macro.mp4",
        in_point_sec: 1.2,
        out_point_sec: 4.5,
        text_overlay: "4K AI Sensor in action",
      },
      {
        cut_index: 3,
        shot_id: "shot_speaker_feature_02",
        source_file_uri: "media/feature_breakdown.mp4",
        in_point_sec: 0.5,
        out_point_sec: 3.8,
        text_overlay: "Ultra-lightweight gimbal",
      },
      {
        cut_index: 4,
        shot_id: "shot_broll_lifestyle_01",
        source_file_uri: "media/lifestyle.mp4",
        in_point_sec: 2.0,
        out_point_sec: 5.6,
        text_overlay: "30-Hour Battery Life 🔋",
      },
      {
        cut_index: 5,
        shot_id: "shot_cta_outro",
        source_file_uri: "media/outro_cta.mp4",
        in_point_sec: 0.0,
        out_point_sec: 3.0,
        text_overlay: brief.call_to_action || "Link in bio to claim yours!",
      },
    ],
  };
}

type SimStage = {
  stage: JobStatus["stage"];
  pct: number;
  msg: string;
  delay: number;
};

const SIMULATED_STAGES: SimStage[] = [
  { stage: "ingesting", pct: 15, msg: "Transcribing clips with Google Cloud Speech-to-Text...", delay: 500 },
  { stage: "indexed", pct: 30, msg: "Footage indexed: 5 atomic shots labeled by Gemini.", delay: 600 },
  { stage: "directing", pct: 50, msg: "Director Agent synthesizing narrative progression...", delay: 700 },
  { stage: "refining", pct: 70, msg: "Snapping cut boundaries to nearest speech timestamps...", delay: 600 },
  { stage: "rendering", pct: 85, msg: "FFmpeg cutting, applying 9:16 crop & burning subtitles...", delay: 800 },
  { stage: "reviewing", pct: 95, msg: "Reviewer validating safe zones and ducking envelopes...", delay: 600 },
  { stage: "completed", pct: 100, msg: "Video finalized and ready for export!", delay: 400 },
];

// ─── Helper: timestamp string ──────────────────────────────────────
function now(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ─── Hook ──────────────────────────────────────────────────────────

export function useChat(backendOnline: boolean | null) {
  const [projectId, setProjectId] = useState(
    () => `vibe_${Math.random().toString(36).substring(2, 8)}`
  );
  const [brief, setBrief] = useState<CreativeBrief>(DEFAULT_BRIEF);
  const [currentPlan, setCurrentPlan] = useState<EditPlan | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRenderingTimeline, setIsRenderingTimeline] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);

  // Conversation state
  const [conversationId, setConversationId] = useState<string | null>(null);
  const streamCleanupRef = useRef<(() => void) | null>(null);
  const streamingMsgRef = useRef<string>("");
  const streamingTurnIdRef = useRef<string | null>(null);

  const [messages, setMessages] = useState<MessageItem[]>([
    {
      id: "msg_init",
      sender: "director",
      text: "Hello! I am your AI Creative Director. Upload raw footage or tell me what 9:16 short-form cut you'd like to create today.",
      timestamp: "Just now",
    },
  ]);

  // ── helpers ──────────────────────────────────────────────────────

  const appendMessages = useCallback((...newMsgs: MessageItem[]) => {
    setMessages((prev) => [...prev, ...newMsgs]);
  }, []);

  const updateStreamingMessage = useCallback((turnId: string, text: string) => {
    setMessages((prev) => {
      const existing = prev.find((m) => m.id === turnId);
      if (existing) {
        return prev.map((m) => (m.id === turnId ? { ...m, text } : m));
      } else {
        return [
          ...prev,
          {
            id: turnId,
            sender: "director" as const,
            text,
            timestamp: now(),
          },
        ];
      }
    });
  }, []);

  // ── Initialize conversation ──────────────────────────────────────

  const initConversation = useCallback(async () => {
    if (!backendOnline) return;

    try {
      const conv = await createConversation(projectId, brief);
      setConversationId(conv.conversation_id);

      // Subscribe to SSE stream
      const cleanup = subscribeToConversationStream(conv.conversation_id, {
        onToken: (text, turnId) => {
          if (turnId) {
            streamingMsgRef.current += text;
            streamingTurnIdRef.current = turnId;
            updateStreamingMessage(turnId, streamingMsgRef.current);
          }
        },
        onAction: (action, prompts, turnId) => {
          // Action received — could trigger re-render, etc.
          if (action === "re-render_ready") {
            // Auto-trigger render if the AI says it's ready
          }
        },
        onPlanUpdate: (plan) => {
          setCurrentPlan(plan);
        },
        onError: (error) => {
          console.error("Stream error:", error);
          setIsGenerating(false);
        },
        onDone: (_prompts, turnId) => {
          setIsGenerating(false);
          // Reset streaming state for next message
          streamingMsgRef.current = "";
          streamingTurnIdRef.current = null;
        },
        onConnected: () => {
          console.log("SSE stream connected");
        },
      });

      streamCleanupRef.current = cleanup;
    } catch (err) {
      console.warn("Failed to create conversation, will use legacy API:", err);
    }
  }, [backendOnline, projectId, brief, updateStreamingMessage]);

  // Initialize conversation on mount when backend is online
  useEffect(() => {
    if (backendOnline && !conversationId) {
      initConversation();
    }

    return () => {
      streamCleanupRef.current?.();
    };
  }, [backendOnline, conversationId, initConversation]);

  // ── New Project ──────────────────────────────────────────────────

  const resetProject = useCallback(() => {
    // Cleanup old SSE stream
    streamCleanupRef.current?.();
    streamCleanupRef.current = null;

    const newId = `vibe_${Math.random().toString(36).substring(2, 8)}`;
    setProjectId(newId);
    setConversationId(null);
    setCurrentPlan(null);
    setVideoUrl(null);
    setJobStatus(null);
    setIsGenerating(false);
    setUploadedCount(0);
    streamingMsgRef.current = "";
    streamingTurnIdRef.current = null;
    setMessages([
      {
        id: `msg_welcome_${Date.now()}`,
        sender: "director",
        text: "New editing session created! Tell me your vision or select an idea below to assemble a fresh 9:16 cut.",
        timestamp: "Just now",
      },
    ]);
  }, []);

  // ── Upload complete ──────────────────────────────────────────────

  const handleUploadComplete = useCallback(
    (count: number) => {
      setUploadedCount((prev) => prev + count);
      const time = now();
      appendMessages(
        {
          id: `msg_upload_${Date.now()}`,
          sender: "system",
          text: `Ingested ${count} raw video clip(s). Ready for Speech-to-Text alignment & editing.`,
          timestamp: time,
        },
        {
          id: `msg_ready_${Date.now()}`,
          sender: "director",
          text: "Clips ready! What narrative direction should I assemble? You can click a starter prompt or type your instructions.",
          timestamp: time,
        },
      );
    },
    [appendMessages],
  );

  // ── Generation pipeline ──────────────────────────────────────────

  const runGenerationPipeline = useCallback(
    async (userPromptText?: string) => {
      setIsGenerating(true);

      const activeBrief: CreativeBrief = {
        ...brief,
        user_prompt: userPromptText || brief.user_prompt,
      };

      // Backend path
      if (backendOnline) {
        try {
          const { job_id, status } = await triggerGeneration(projectId, activeBrief);
          setJobStatus(status);

          subscribeToJobStream(
            job_id,
            (updatedStatus) => {
              setJobStatus(updatedStatus);
              if (updatedStatus.edit_plan) setCurrentPlan(updatedStatus.edit_plan);
            },
            (finalStatus) => {
              setIsGenerating(false);
              if (finalStatus.stage === "completed") {
                const url = getVideoUrl(`${projectId}_final.mp4`);
                setVideoUrl(url);
                appendMessages({
                  id: `msg_done_${Date.now()}`,
                  sender: "director",
                  text: "✨ Edit finalized! The video has been trimmed to speech pauses, 9:16 reframed, and captions burned in safe boundaries.",
                  timestamp: now(),
                  plan: finalStatus.edit_plan,
                  videoUrl: url,
                });
              } else if (finalStatus.stage === "failed") {
                appendMessages({
                  id: `msg_fail_${Date.now()}`,
                  sender: "system",
                  text: `Pipeline failed: ${finalStatus.error || "Unknown error"}`,
                  timestamp: now(),
                });
              }
            },
            () => setIsGenerating(false),
          );
          return;
        } catch (err) {
          console.warn("Backend generate failed, falling back to simulated generation:", err);
        }
      }

      // Offline simulation fallback
      const simulatedPlan = buildSimulatedPlan(projectId, brief);

      for (const step of SIMULATED_STAGES) {
        setJobStatus({
          job_id: `job_sim_${Date.now()}`,
          project_id: projectId,
          stage: step.stage,
          progress_percentage: step.pct,
          message: step.msg,
          edit_plan: simulatedPlan,
        });
        await new Promise((r) => setTimeout(r, step.delay));
      }

      setCurrentPlan(simulatedPlan);
      setIsGenerating(false);
      const demoUrl =
        "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4";
      setVideoUrl(demoUrl);

      appendMessages({
        id: `msg_final_${Date.now()}`,
        sender: "director",
        text: `✨ Autonomous cut completed! I assembled ${simulatedPlan.cuts.length} cuts (${simulatedPlan.total_target_duration}s total) with speech-synced subtitle punchlines. You can edit any cut or converse with me to fine-tune.`,
        timestamp: now(),
        plan: simulatedPlan,
        videoUrl: demoUrl,
      });
    },
    [backendOnline, brief, projectId, appendMessages],
  );

  // ── Send chat message ────────────────────────────────────────────

  const handleSendMessage = useCallback(
    async (text: string) => {
      const userMsg: MessageItem = {
        id: `user_${Date.now()}`,
        sender: "user",
        text,
        timestamp: now(),
      };
      appendMessages(userMsg);

      const lower = text.toLowerCase();

      // Initial generation prompt detection
      if (
        !currentPlan &&
        (lower.includes("generate") || lower.includes("create") || lower.includes("reel") || lower.includes("short"))
      ) {
        await runGenerationPipeline(text);
        return;
      }

      // ── New conversation-based path ──────────────────────────────
      if (conversationId && backendOnline) {
        setIsGenerating(true);
        streamingMsgRef.current = "";
        try {
          await sendConversationMessage(conversationId, text);
          // Response will arrive via SSE stream — the onToken/onDone callbacks
          // in the stream subscription handle message rendering and state updates
          return;
        } catch (err) {
          console.warn("Conversation message failed, falling back to legacy:", err);
          setIsGenerating(false);
        }
      }

      // ── Legacy fallback (stateless /chat endpoint) ───────────────
      setIsGenerating(true);
      try {
        const response = await sendChatMessage(projectId, text, currentPlan, brief);
        setIsGenerating(false);

        if (response.suggested_plan) setCurrentPlan(response.suggested_plan);
        if (response.suggested_brief) setBrief(response.suggested_brief);

        let renderedUrl: string | undefined;
        if (response.action === "re-render_ready" && (response.suggested_plan || currentPlan)) {
          setIsRenderingTimeline(true);
          const planToRender = response.suggested_plan || currentPlan!;
          const renderRes = await renderCustomPlan(projectId, planToRender);
          renderedUrl = renderRes.video_url;
          setVideoUrl(renderedUrl);
          setIsRenderingTimeline(false);
        }

        appendMessages({
          id: `ai_${Date.now()}`,
          sender: "director",
          text: response.message,
          timestamp: now(),
          plan: response.suggested_plan || undefined,
          videoUrl: renderedUrl,
        });
      } catch {
        setIsGenerating(false);
      }
    },
    [currentPlan, brief, projectId, conversationId, backendOnline, appendMessages, runGenerationPipeline],
  );

  // ── Update plan (from timeline editor) ───────────────────────────

  const handleUpdatePlan = useCallback(
    async (updated: EditPlan) => {
      setCurrentPlan(updated);

      // Push to server if conversation exists
      if (conversationId && backendOnline) {
        try {
          await updateConversationPlan(conversationId, updated);
        } catch (err) {
          console.warn("Failed to sync plan update to server:", err);
        }
      }

      appendMessages({
        id: `msg_timeline_edit_${Date.now()}`,
        sender: "system",
        text: `Timeline updated to Revision ${updated.revision} (${updated.total_target_duration}s total).`,
        timestamp: now(),
        plan: updated,
      });
    },
    [conversationId, backendOnline, appendMessages],
  );

  // ── Re-render timeline ───────────────────────────────────────────

  const handleReRender = useCallback(async () => {
    if (!currentPlan) return;
    setIsRenderingTimeline(true);

    try {
      // Use conversation-based render if available
      let res: { video_url: string };
      if (conversationId && backendOnline) {
        res = await triggerConversationRender(conversationId);
      } else {
        res = await renderCustomPlan(projectId, currentPlan);
      }

      setVideoUrl(res.video_url);
      setIsRenderingTimeline(false);

      appendMessages({
        id: `msg_rerender_${Date.now()}`,
        sender: "director",
        text: `🎬 Re-rendered timeline with Revision ${currentPlan.revision} (${currentPlan.total_target_duration}s). Subtitles burned in platform-safe boundaries.`,
        timestamp: now(),
        plan: currentPlan,
        videoUrl: res.video_url,
      });
    } catch {
      setIsRenderingTimeline(false);
    }
  }, [currentPlan, conversationId, backendOnline, projectId, appendMessages]);

  return {
    projectId,
    brief,
    currentPlan,
    videoUrl,
    jobStatus,
    isGenerating,
    isRenderingTimeline,
    uploadedCount,
    messages,
    conversationId,

    resetProject,
    handleUploadComplete,
    handleSendMessage,
    handleUpdatePlan,
    handleReRender,
  } as const;
}
