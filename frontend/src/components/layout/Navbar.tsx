"use client";

import React from "react";
import { Sun, Moon, UploadCloud, Plus, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface NavbarProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  backendOnline: boolean | null;
  uploadedCount: number;
  onOpenUpload: () => void;
  onNewProject: () => void;
  projectId: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  theme,
  onToggleTheme,
  backendOnline,
  uploadedCount,
  onOpenUpload,
  onNewProject,
  projectId,
}) => {
  return (
    <header className="w-full h-12 flex items-center justify-between px-5 border-b border-border bg-background/80 backdrop-blur-md flex-shrink-0 z-30">
      {/* Brand & Project Info */}
      <div className="flex items-center gap-2.5">
        <div
          onClick={onNewProject}
          className="flex items-center gap-2 cursor-pointer group"
        >
          <div className="w-6 h-6 rounded-lg bg-primary text-primary-foreground flex items-center justify-center shadow-xs">
            <Video size={13} strokeWidth={2.5} />
          </div>
          <span className="font-semibold text-sm tracking-tight text-foreground">
            VibeShorts
          </span>
        </div>

        <Badge variant="subtle" className="text-[10px] font-mono font-normal py-0 px-2 rounded-lg">
          {projectId}
        </Badge>
      </div>

      {/* Right Controls: Minimalist & Compact */}
      <div className="flex items-center gap-1.5">
        {/* Clips button */}
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenUpload}
          className="rounded-xl h-7 px-2.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <UploadCloud size={13} className="mr-1.5 text-muted-foreground" />
          Clips {uploadedCount > 0 && <span className="ml-1 font-semibold text-foreground">({uploadedCount})</span>}
        </Button>

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleTheme}
          title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
          className="rounded-xl h-7 w-7 text-muted-foreground hover:text-foreground"
        >
          {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
        </Button>

        {/* New Chat */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onNewProject}
          title="Start new conversation"
          className="rounded-xl h-7 w-7 text-muted-foreground hover:text-foreground"
        >
          <Plus size={15} />
        </Button>
      </div>
    </header>
  );
};
