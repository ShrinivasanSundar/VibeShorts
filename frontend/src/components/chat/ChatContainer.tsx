"use client";

import React, { useRef, useEffect } from "react";
import { Sparkles, User, CheckCircle2 } from "lucide-react";
import { EditPlan, JobStatus } from "@/lib/api";
import { PlanCard } from "./PlanCard";
import { InlineVideoPlayer } from "./InlineVideoPlayer";
import { VideoGenerationLoader } from "@/components/ui/video-generation-loader";

export interface MessageItem {
  id: string;
  sender: "user" | "director" | "system";
  text: string;
  timestamp: string;
  plan?: EditPlan;
  jobStatus?: JobStatus;
  videoUrl?: string;
}

interface ChatContainerProps {
  messages: MessageItem[];
  isGenerating: boolean;
  activeJob: JobStatus | null;
  onSelectCut: (cutIndex: number) => void;
  onOpenEditor: () => void;
}

export const ChatContainer: React.FC<ChatContainerProps> = ({
  messages,
  isGenerating,
  activeJob,
  onSelectCut,
  onOpenEditor,
}) => {

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isGenerating, activeJob]);


  // Check if an active conversation with user input has started
  const hasUserMessage = messages.some((m) => m.sender === "user");

  return (
    <div
      className={`flex-1 overflow-y-auto px-2 py-4 flex flex-col gap-3.5 w-full mx-auto ${
        !hasUserMessage ? "justify-center items-center" : ""
      }`}
    >
      {/* Centered Welcome State */}
      {!hasUserMessage && (
        <div className="my-auto py-8 text-center flex flex-col items-center justify-center gap-3.5 max-w-md mx-auto">
          <div className="w-11 h-11 rounded-2xl bg-primary text-primary-foreground flex items-center justify-center shadow-xs">
            <Sparkles size={20} strokeWidth={2.2} />
          </div>

          <div className="flex flex-col gap-1.5 items-center">
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              What video would you like to direct?
            </h2>

            <p className="text-xs text-muted-foreground leading-relaxed max-w-sm">
              Hello! I am your AI Creative Director. Upload raw footage or describe what 9:16 short-form cut you&apos;d like to create today.
            </p>
          </div>
        </div>
      )}

      {/* Message Stream */}
      {hasUserMessage &&
        messages.map((msg) => {
        const isUser = msg.sender === "user";
        const isSystem = msg.sender === "system";

        if (isSystem) {
          return (
            <div
              key={msg.id}
              className="message-enter self-center bg-muted/40 border border-border/60 rounded-full px-2.5 py-0.5 text-[11px] text-muted-foreground font-mono flex items-center gap-1.5"
            >
              <CheckCircle2 size={11} className="text-emerald-500" />
              <span>{msg.text}</span>
            </div>
          );
        }

        return (
          <div
            key={msg.id}
            className={`message-enter flex items-start gap-2 max-w-[85%] ${
              isUser ? "self-end flex-row-reverse" : "self-start flex-row"
            }`}
          >
            {/* Small Avatar */}
            <div
              className={`w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 text-xs ${
                isUser
                  ? "bg-secondary text-secondary-foreground border border-border"
                  : "bg-primary text-primary-foreground"
              }`}
            >
              {isUser ? <User size={12} /> : <Sparkles size={12} />}
            </div>

            {/* Bubble */}
            <div className="flex flex-col gap-1 min-w-0">
              <div
                className={`text-[10px] text-muted-foreground px-1 ${
                  isUser ? "self-end" : "self-start"
                }`}
              >
                <span>{isUser ? "You" : "Director"}</span> • <span>{msg.timestamp}</span>
              </div>

              <div
                className={`text-xs leading-relaxed ${
                  isUser
                    ? "rounded-2xl rounded-tr-sm bg-primary text-primary-foreground px-3.5 py-2 shadow-xs"
                    : "rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-foreground shadow-xs"
                }`}
              >
                <div>{msg.text}</div>

                {/* Inline Video Player */}
                {msg.videoUrl && (
                  <InlineVideoPlayer
                    src={msg.videoUrl}
                    duration={msg.plan?.total_target_duration}
                    onOpenEditor={onOpenEditor}
                  />
                )}

                {/* Inline Plan Card */}
                {msg.plan && (
                  <PlanCard
                    plan={msg.plan}
                    onSelectCut={onSelectCut}
                    onOpenFullEditor={onOpenEditor}
                  />
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Pipeline Loader for actual video rendering jobs */}
      {isGenerating && activeJob && (
        <div className="w-full self-center message-enter">
          <VideoGenerationLoader
            progress={activeJob.progress_percentage || 45}
            stageName={activeJob.message || "Directing cut sequence and audio clocks..."}
          />
        </div>
      )}

      {/* Director Typing Indicator while waiting for streaming response */}
      {isGenerating && !activeJob && messages.length > 0 && messages[messages.length - 1].sender === "user" && (
        <div className="message-enter flex items-center gap-2 self-start">
          <div className="w-6 h-6 rounded-lg bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0 text-xs">
            <Sparkles size={12} />
          </div>
          <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-foreground shadow-xs flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.3s]" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.15s]" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce" />
          </div>
        </div>
      )}

      <div ref={bottomRef} className="h-2" />
    </div>
  );
};
