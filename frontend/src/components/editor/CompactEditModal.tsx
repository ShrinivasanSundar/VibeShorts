"use client";

import React, { useState } from "react";
import { X, Trash2, Plus, RefreshCw, Check } from "lucide-react";
import { EditPlan, EditPlanEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface CompactEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  plan: EditPlan | null;
  onUpdatePlan: (updatedPlan: EditPlan) => void;
  onTriggerReRender: () => void;
  isRendering?: boolean;
  initialCutIndex?: number | null;
  videoSrc?: string | null;
}

export const CompactEditModal: React.FC<CompactEditModalProps> = ({
  isOpen,
  onClose,
  plan,
  onUpdatePlan,
  onTriggerReRender,
  isRendering,
  initialCutIndex,
  videoSrc,
}) => {
  const [selectedCutIndex, setSelectedCutIndex] = useState<number>(initialCutIndex || 1);
  const [inPoint, setInPoint] = useState<number>(0);
  const [outPoint, setOutPoint] = useState<number>(3);
  const [caption, setCaption] = useState<string>("");
  const [isSaved, setIsSaved] = useState(false);

  if (!isOpen || !plan) return null;

  const cuts = plan.cuts || [];
  const selectedCut = cuts.find((c) => c.cut_index === selectedCutIndex) || cuts[0];

  const handleSelectCut = (cut: EditPlanEntry) => {
    setSelectedCutIndex(cut.cut_index);
    setInPoint(cut.in_point_sec);
    setOutPoint(cut.out_point_sec);
    setCaption(cut.text_overlay || "");
    setIsSaved(false);
  };

  const handleApplyCut = () => {
    if (!selectedCut) return;
    const newCuts = cuts.map((c) => {
      if (c.cut_index === selectedCut.cut_index) {
        return {
          ...c,
          in_point_sec: Number(inPoint.toFixed(2)),
          out_point_sec: Number(outPoint.toFixed(2)),
          text_overlay: caption.trim() || undefined,
        };
      }
      return c;
    });

    const totalDur = Number(
      newCuts.reduce((acc, c) => acc + (c.out_point_sec - c.in_point_sec), 0).toFixed(1)
    );

    const updatedPlan: EditPlan = {
      ...plan,
      revision: plan.revision + 1,
      total_target_duration: totalDur,
      cuts: newCuts,
    };

    onUpdatePlan(updatedPlan);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 1200);
  };

  const handleDeleteCut = (cutIndex: number) => {
    const newCuts = cuts
      .filter((c) => c.cut_index !== cutIndex)
      .map((c, idx) => ({ ...c, cut_index: idx + 1 }));

    const totalDur = Number(
      newCuts.reduce((acc, c) => acc + (c.out_point_sec - c.in_point_sec), 0).toFixed(1)
    );

    onUpdatePlan({
      ...plan,
      revision: plan.revision + 1,
      total_target_duration: totalDur,
      cuts: newCuts,
    });
    if (newCuts.length > 0) {
      handleSelectCut(newCuts[0]);
    }
  };

  const handleAddCut = () => {
    const nextIdx = cuts.length + 1;
    const newCut: EditPlanEntry = {
      cut_index: nextIdx,
      shot_id: `shot_broll_${nextIdx}`,
      source_file_uri: cuts[0]?.source_file_uri || "media/clip.mp4",
      in_point_sec: 0.0,
      out_point_sec: 2.5,
      text_overlay: "Key Highlight",
    };

    const newCuts = [...cuts, newCut];
    const totalDur = Number(
      newCuts.reduce((acc, c) => acc + (c.out_point_sec - c.in_point_sec), 0).toFixed(1)
    );

    onUpdatePlan({
      ...plan,
      revision: plan.revision + 1,
      total_target_duration: totalDur,
      cuts: newCuts,
    });
    handleSelectCut(newCut);
  };

  return (
    <div className="compact-modal-backdrop" onClick={onClose}>
      <div
        className="w-full max-w-lg p-5 rounded-2xl border border-border bg-card shadow-lg flex flex-col gap-3.5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between pb-1 border-b border-border/70">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm text-foreground">Timeline Editor</h3>
            <Badge variant="subtle" className="text-[10px] font-mono px-1.5 py-0">
              Rev {plan.revision} • {plan.total_target_duration}s
            </Badge>
          </div>

          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-6 w-6 rounded-lg text-muted-foreground"
          >
            <X size={14} />
          </Button>
        </div>

        {/* Video Preview if available */}
        {videoSrc && (
          <div className="w-full max-h-40 bg-black rounded-xl overflow-hidden flex items-center justify-center border border-border/80">
            <video
              src={videoSrc}
              controls
              playsInline
              className="w-full h-full max-h-40 object-contain"
            />
          </div>
        )}

        {/* Cuts Strip */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground text-[11px] font-medium">
              Cuts Sequence ({cuts.length})
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleAddCut}
              className="h-5 px-1.5 text-[11px] rounded-md text-muted-foreground hover:text-foreground"
            >
              <Plus size={12} className="mr-0.5" />
              Add Cut
            </Button>
          </div>

          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none">
            {cuts.map((cut) => {
              const isSelected = selectedCut?.cut_index === cut.cut_index;
              const dur = (cut.out_point_sec - cut.in_point_sec).toFixed(1);
              return (
                <div
                  key={cut.cut_index}
                  onClick={() => handleSelectCut(cut)}
                  className={`flex-shrink-0 w-24 p-1.5 rounded-xl border text-xs cursor-pointer transition-colors ${
                    isSelected
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border/80 bg-background/50 hover:bg-accent/40 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <div className="flex justify-between items-center text-[10px] font-mono font-semibold mb-0.5">
                    <span>#{cut.cut_index}</span>
                    <span>{dur}s</span>
                  </div>
                  <div className="truncate text-[11px] font-medium">
                    {cut.shot_id}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Selected Cut Controls */}
        {selectedCut && (
          <div className="p-3 rounded-xl border border-border/70 bg-muted/20 flex flex-col gap-2.5">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-foreground text-xs">
                Cut #{selectedCut.cut_index}: {selectedCut.shot_id}
              </span>

              {cuts.length > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDeleteCut(selectedCut.cut_index)}
                  className="h-6 px-1.5 text-destructive hover:text-destructive text-[11px] hover:bg-destructive/10 rounded-lg"
                >
                  <Trash2 size={11} className="mr-1" />
                  Delete
                </Button>
              )}
            </div>

            {/* In / Out Sliders */}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>In-Point</span>
                  <span className="font-mono font-medium text-foreground">{inPoint}s</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0.1, outPoint - 0.5)}
                  step={0.1}
                  value={inPoint}
                  onChange={(e) => setInPoint(Number(e.target.value))}
                  className="w-full accent-primary"
                />
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>Out-Point</span>
                  <span className="font-mono font-medium text-foreground">{outPoint}s</span>
                </div>
                <input
                  type="range"
                  min={inPoint + 0.5}
                  max={Math.max(10, outPoint + 3)}
                  step={0.1}
                  value={outPoint}
                  onChange={(e) => setOutPoint(Number(e.target.value))}
                  className="w-full accent-primary"
                />
              </div>
            </div>

            {/* Subtitle Input */}
            <div className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">Subtitle Overlay</span>
              <div className="flex gap-1.5">
                <Input
                  type="text"
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  placeholder="e.g. Revolutionary 4K AI Sensor..."
                  className="h-7 text-xs rounded-lg"
                />
                <Button
                  size="sm"
                  onClick={handleApplyCut}
                  className="h-7 px-2.5 rounded-lg text-xs"
                >
                  {isSaved ? <Check size={12} /> : "Save"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-1">
          <Button variant="outline" size="sm" onClick={onClose} className="rounded-xl h-7 text-xs">
            Close
          </Button>

          <Button
            size="sm"
            onClick={() => {
              handleApplyCut();
              onTriggerReRender();
            }}
            disabled={isRendering}
            className="rounded-xl h-7 text-xs"
          >
            <RefreshCw size={12} className={`mr-1.5 ${isRendering ? "animate-spin" : ""}`} />
            {isRendering ? "Rendering..." : "Re-render Timeline"}
          </Button>
        </div>
      </div>
    </div>
  );
};
