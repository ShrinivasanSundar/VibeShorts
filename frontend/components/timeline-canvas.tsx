"use client";

import { useRef } from "react";
import { Save, X } from "lucide-react";
import { useWorkspace } from "../lib/workspace";
import { useStudio } from "../lib/studio-store";
import { CompositionPreview } from "./preview";
import { TimelineEditor, ClipInspector } from "./timeline";
import { MediaThumbnail } from "./media-thumbnail";

export function TimelineCanvas({ onClose }: { onClose: () => void }) {
  const w = useWorkspace();
  const s = useStudio();
  const pane = useRef<HTMLElement>(null);
  return (
    <aside
      ref={pane}
      className="chat-timeline-canvas"
      aria-label="Video timeline canvas"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <header>
        <div>
          <strong>Edit your video</strong>
          <small>{s.dirty ? "Unsaved changes" : "All changes saved"}</small>
        </div>
        <button
          className="chat-button"
          disabled={w.busy || !s.dirty}
          onClick={() => void w.action(w.save)}
        >
          <Save size={15} /> Save revision
        </button>
        <button aria-label="Back to preview" onClick={onClose}>
          <X size={19} /> Back to preview
        </button>
      </header>
      <nav className="editor-scenes" aria-label="Scenes">
        <h3>Scenes</h3>
        {s.timeline.clips
          .filter((c) => c.kind === "video" || c.kind === "image")
          .map((clip, i) => (
            <button
              key={clip.id}
              aria-pressed={s.selected === clip.id}
              onClick={() => {
                s.select(clip.id);
                s.seek(clip.start);
              }}
            >
              {clip.artifact_id && (
                <MediaThumbnail
                  projectId={w.projectId}
                  artifactId={clip.artifact_id}
                  kind={clip.kind}
                  sourceIn={clip.source_in}
                  title={clip.id}
                />
              )}
              <span>
                {String(i + 1).padStart(2, "0")} {clip.id}
                <small>{clip.duration.toFixed(1)}s</small>
              </span>
            </button>
          ))}
      </nav>
      <CompositionPreview projectId={w.projectId} artifactId={w.head} />
      <TimelineEditor />
      <div className="chat-canvas-properties">
        <h3>Video settings</h3>
        <label>
          Video duration (s)
          <input
            type="number"
            min={1}
            max={120}
            value={s.timeline.duration_seconds}
            onChange={(e) => {
              const duration = Math.max(
                1,
                Math.min(120, Number(e.target.value) || 1),
              );
              s.edit({
                ...s.timeline,
                duration_seconds: duration,
                clips: s.timeline.clips
                  .filter((c) => c.start < duration)
                  .map((c) => ({
                    ...c,
                    duration: Math.min(c.duration, duration - c.start),
                  })),
              });
            }}
          />
        </label>
        <label>
          Title
          <input
            maxLength={120}
            value={s.timeline.title}
            onChange={(e) => s.edit({ ...s.timeline, title: e.target.value })}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={s.timeline.clips
              .filter((c) => c.kind === "text")
              .some((c) => !c.hidden)}
            onChange={(e) =>
              s.edit({
                ...s.timeline,
                clips: s.timeline.clips.map((c) =>
                  c.kind === "text" ? { ...c, hidden: !e.target.checked } : c,
                ),
              })
            }
          />{" "}
          Show captions
        </label>
        <div className="field-pair">
          <label>
            Background
            <input
              type="color"
              value={s.timeline.background}
              onChange={(e) =>
                s.edit({ ...s.timeline, background: e.target.value })
              }
            />
          </label>
          <label>
            Text color
            <input
              type="color"
              value={s.timeline.foreground}
              onChange={(e) =>
                s.edit({ ...s.timeline, foreground: e.target.value })
              }
            />
          </label>
        </div>
        <button
          className="chat-button"
          onClick={() => {
            const clip = {
              id: "text-" + crypto.randomUUID().slice(0, 8),
              kind: "text" as const,
              artifact_id: null,
              track: 2,
              start: s.time,
              duration: Math.min(3, s.timeline.duration_seconds - s.time),
              source_in: 0,
              text: "Your text",
              volume: 0,
              fade_in: 0,
              fade_out: 0,
              hidden: false,
            };
            if (clip.duration > 0) {
              s.edit({ ...s.timeline, clips: [...s.timeline.clips, clip] });
              s.select(clip.id);
            }
          }}
        >
          Add text
        </button>
        <ClipInspector />
      </div>
    </aside>
  );
}
