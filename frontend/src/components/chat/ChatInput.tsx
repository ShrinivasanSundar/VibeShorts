"use client";

import React, { useState, useRef, useEffect } from "react";
import { ArrowUp, Paperclip } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onOpenUpload: () => void;
  uploadedCount: number;
  isLoading: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  onOpenUpload,
  uploadedCount,
  isLoading,
}) => {

  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!text.trim() || isLoading) return;
    onSendMessage(text.trim());
    setText("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Auto-resize
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [text]);

  return (
    <div className="w-full max-w-2xl mx-auto flex flex-col gap-2">
      {/* Main Minimalist Chat Input Box with Rounded-2xl Border */}
      <div className="relative rounded-2xl border border-border bg-card p-2 shadow-xs transition-colors focus-within:border-foreground/30 focus-within:ring-1 focus-within:ring-ring/20">

        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask AI Director to generate or edit a 9:16 video..."
          className="w-full bg-transparent border-0 outline-none text-foreground placeholder:text-muted-foreground text-xs leading-relaxed resize-none px-2 py-1 max-h-28"
        />

        <div className="flex items-center justify-between pt-1">
          {/* Attach footage button */}
          <button
            type="button"
            onClick={onOpenUpload}
            title="Attach raw footage"
            className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground px-2 py-1 rounded-lg text-xs hover:bg-muted/50 transition-colors"
          >
            <Paperclip size={13} />
            <span className="text-[11px]">
              {uploadedCount > 0 ? `${uploadedCount} clip(s)` : "Attach clips"}
            </span>
          </button>

          {/* Minimalist Send Button */}
          <Button
            type="button"
            size="icon"
            onClick={() => handleSubmit()}
            disabled={!text.trim() || isLoading}
            className="h-6 w-6 rounded-lg transition-transform active:scale-95"
          >
            <ArrowUp size={13} strokeWidth={2.5} />
          </Button>
        </div>
      </div>
    </div>
  );
};
