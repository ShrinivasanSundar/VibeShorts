"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface VideoGenerationLoaderProps {
  progress?: number;
  stageName?: string;
  className?: string;
}

export const VideoGenerationLoader: React.FC<VideoGenerationLoaderProps> = ({
  progress = 45,
  stageName = "Synthesizing 9:16 frame cuts...",
  className,
}) => {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-card p-4 shadow-sm flex flex-col items-center justify-center text-center max-w-sm mx-auto my-3 overflow-hidden",
        className
      )}
    >
      {/* Animated Video Generation Reel / Frame Scanloader (GIF-style animation) */}
      <div className="relative w-36 h-24 mb-3 rounded-xl bg-muted/40 border border-border/70 overflow-hidden flex items-center justify-center">
        {/* Film Strip Perforations top & bottom */}
        <div className="absolute top-1 inset-x-0 flex justify-between px-1.5 opacity-40">
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
        </div>
        <div className="absolute bottom-1 inset-x-0 flex justify-between px-1.5 opacity-40">
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
          <div className="w-1.5 h-1 rounded-xs bg-foreground" />
        </div>

        {/* Central Camera Shutter / AI Frame Interpolation Animation */}
        <div className="relative flex items-center justify-center">
          {/* Outer rotating aperture ring */}
          <div
            className="w-12 h-12 rounded-full border-2 border-dashed border-primary/60"
            style={{ animation: "spin 6s linear infinite" }}
          />

          {/* Inner pulsating video frame */}
          <div
            className="absolute w-8 h-8 rounded-lg bg-primary/10 border border-primary/40 flex items-center justify-center"
            style={{ animation: "pulse 1.8s ease-in-out infinite" }}
          >
            <div className="w-2.5 h-2.5 rounded-full bg-primary animate-ping opacity-75" />
          </div>

          {/* Scanning Laser / Playhead line traversing across */}
          <div
            className="absolute -inset-y-6 w-0.5 bg-gradient-to-b from-transparent via-primary to-transparent"
            style={{
              animation: "scanline 2s ease-in-out infinite alternate",
            }}
          />
        </div>

        {/* Mini 9:16 Aspect Indicator Tag */}
        <span className="absolute bottom-1.5 right-2 text-[9px] font-mono font-semibold text-muted-foreground/80">
          9:16
        </span>
      </div>

      {/* Progress & Status */}
      <div className="w-full flex items-center justify-between text-xs mb-1.5">
        <span className="font-medium text-foreground text-[11px] truncate max-w-[200px]">
          {stageName}
        </span>
        <span className="font-mono text-muted-foreground text-[11px] font-semibold">
          {progress}%
        </span>
      </div>

      {/* Minimal Progress Bar */}
      <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-300 rounded-full"
          style={{ width: `${Math.max(6, progress)}%` }}
        />
      </div>
    </div>
  );
};

