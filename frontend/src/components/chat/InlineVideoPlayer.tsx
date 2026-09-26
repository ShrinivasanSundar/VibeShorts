"use client";

import React, { useRef, useState } from "react";
import { Play, Pause, Download, Sliders, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface InlineVideoPlayerProps {
  src: string;
  onOpenEditor?: () => void;
  title?: string;
  duration?: number;
}

export const InlineVideoPlayer: React.FC<InlineVideoPlayerProps> = ({
  src,
  onOpenEditor,
  title = "Rendered Cut",
  duration,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleDownload = () => {
    const a = document.createElement("a");
    a.href = src;
    a.download = "vibeshorts_final.mp4";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="mt-2.5 rounded-2xl border border-border bg-card p-3 shadow-xs max-w-[280px]">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-xs text-foreground">{title}</span>
          <Badge variant="subtle" className="text-[10px] px-1.5 py-0 font-mono">
            9:16
          </Badge>
        </div>

        {duration && (
          <span className="text-[11px] font-mono text-muted-foreground font-medium">
            {duration}s
          </span>
        )}
      </div>

      {/* Video Container with rounded-xl border */}
      <div className="relative w-full aspect-[9/16] max-h-[360px] bg-black rounded-xl overflow-hidden flex items-center justify-center border border-border/80">
        <video
          ref={videoRef}
          src={src}
          playsInline
          loop
          muted={isMuted}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onClick={togglePlay}
          className="w-full h-full object-cover cursor-pointer"
        />

        {/* Minimal Play Overlay if paused */}
        {!isPlaying && (
          <button
            onClick={togglePlay}
            className="absolute w-10 h-10 rounded-full bg-black/60 border border-white/20 text-white flex items-center justify-center backdrop-blur-xs hover:scale-105 transition-transform"
          >
            <Play size={16} className="ml-0.5" />
          </button>
        )}

        {/* Minimal Controls */}
        <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between bg-black/50 backdrop-blur-sm px-2 py-1 rounded-lg">
          <button
            onClick={togglePlay}
            className="text-white hover:text-white/80 transition-colors"
          >
            {isPlaying ? <Pause size={12} /> : <Play size={12} />}
          </button>

          <button
            onClick={() => setIsMuted(!isMuted)}
            className="text-white hover:text-white/80 transition-colors"
          >
            {isMuted ? <VolumeX size={12} /> : <Volume2 size={12} />}
          </button>
        </div>
      </div>

      {/* Footer Minimal Buttons */}
      <div className="flex items-center gap-1.5 mt-2">
        {onOpenEditor && (
          <Button
            variant="outline"
            size="sm"
            onClick={onOpenEditor}
            className="flex-1 h-7 rounded-lg text-xs"
          >
            <Sliders size={12} className="mr-1" />
            Edit
          </Button>
        )}

        <Button
          size="sm"
          onClick={handleDownload}
          className="flex-1 h-7 rounded-lg text-xs"
        >
          <Download size={12} className="mr-1" />
          Export
        </Button>
      </div>
    </div>
  );
};
