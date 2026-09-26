"use client";

import React from "react";
import { EditPlan, EditPlanEntry } from "@/lib/api";
import { Sliders, Video } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface PlanCardProps {
  plan: EditPlan;
  onSelectCut?: (cutIndex: number) => void;
  onOpenFullEditor?: () => void;
}

export const PlanCard: React.FC<PlanCardProps> = ({
  plan,
  onSelectCut,
  onOpenFullEditor,
}) => {
  return (
    <Card className="mt-2.5 rounded-2xl border-border bg-card shadow-xs overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-border/70 bg-muted/20">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-primary text-primary-foreground flex items-center justify-center">
            <Video size={11} />
          </div>
          <span className="font-medium text-xs text-foreground">
            Edit Plan (Rev {plan.revision})
          </span>
          <Badge variant="subtle" className="text-[10px] px-1.5 py-0 font-mono">
            {plan.total_target_duration}s
          </Badge>
        </div>

        {onOpenFullEditor && (
          <Button
            variant="outline"
            size="sm"
            onClick={onOpenFullEditor}
            className="h-6 px-2 text-[11px] rounded-lg"
          >
            <Sliders size={11} className="mr-1 text-muted-foreground" />
            Edit Cuts
          </Button>
        )}
      </div>

      {/* Cuts List */}
      <div className="p-2.5 flex flex-col gap-1.5">
        {plan.cuts.map((cut: EditPlanEntry) => {
          const duration = (cut.out_point_sec - cut.in_point_sec).toFixed(1);
          return (
            <div
              key={cut.cut_index}
              onClick={() => onSelectCut && onSelectCut(cut.cut_index)}
              className="group flex items-center justify-between p-2 rounded-xl border border-border/70 bg-background/50 hover:bg-accent/40 hover:border-border transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">
                  #{cut.cut_index}
                </span>

                <span className="text-xs font-medium text-foreground truncate max-w-[160px]">
                  {cut.shot_id}
                </span>

                {cut.text_overlay && (
                  <span className="text-[11px] text-muted-foreground italic truncate max-w-[180px]">
                    &ldquo;{cut.text_overlay}&rdquo;
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span className="text-[11px] font-mono text-muted-foreground">
                  {duration}s
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};
