"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { Check, Clapperboard, Sparkles } from "lucide-react";
import { useWorkspace } from "../lib/workspace";
import type { ConversationState, ProductionStep } from "../lib/studio-types";
import { PrivateMedia } from "./private-media";

const CompositionPreview = dynamic(() =>
  import("./preview").then((m) => m.CompositionPreview),
);
const active = (step: ProductionStep) =>
  ["queued", "running", "waiting_for_jobs"].includes(step.status);
const label = (step: ProductionStep) =>
  step.status === "succeeded"
    ? "Ready"
    : step.status === "submission_unknown"
      ? "Checking provider request"
      : step.status === "pending"
        ? "Waiting"
        : step.status.replaceAll("_", " ");

export function ProductionPlan({ state }: { state?: ConversationState }) {
  const p = state?.production;
  if (!p?.storyboard) return null;
  const frames = p.scenes.map((scene) => scene.frame),
    scenes = p.scenes.map((scene) =>
      scene.video.status === "pending" ? scene.generation : scene.video,
    );
  const group = (steps: ProductionStep[]) =>
    steps.length && steps.every((step) => step.status === "succeeded")
      ? "Ready"
      : steps.some((step) => step.status === "failed")
        ? "Needs attention"
        : steps.some((step) => step.status === "submission_unknown")
          ? "Checking request"
          : steps.some(active)
            ? "In progress"
            : "Waiting";
  const steps = [
    [
      "Plan",
      state?.run?.workflow?.stage === "storyboard"
        ? "Review required"
        : "Approved",
    ],
    ["Frames", group(frames)],
    ["Scenes", group(scenes)],
    [
      "Music",
      group([p.music.status === "pending" ? p.music_generation : p.music]),
    ],
    ["Final cut", group([p.draft])],
  ];
  return (
    <section className="production-plan" aria-label="Production plan">
      <header>
        <Sparkles size={17} />
        <strong>Your video plan</strong>
        <span>
          {p.scenes.length} scenes · {p.storyboard.duration_seconds}s
        </span>
      </header>
      <ol>
        {steps.map(([name, status]) => (
          <li
            key={name}
            className={
              status === "Ready" || status === "Approved" ? "complete" : ""
            }
          >
            <span>
              {status === "Ready" || status === "Approved" ? (
                <Check size={14} />
              ) : (
                <i />
              )}
            </span>
            <strong>{name}</strong>
            <small>{status}</small>
          </li>
        ))}
      </ol>
      {p.affected_scene_ids.length > 0 && (
        <p>
          Scenes to regenerate: {p.affected_scene_ids.join(", ")}. Other
          completed media will be reused.
        </p>
      )}
    </section>
  );
}

export function ProductionView({
  state,
  onEdit,
  onRevise,
  onExport,
  busy,
  pendingPreview,
}: {
  state?: ConversationState;
  onEdit: () => void;
  onRevise: (scene?: string) => void;
  onExport: () => void;
  busy: boolean;
  pendingPreview: boolean;
}) {
  const w = useWorkspace();
  const p = state?.production;
  const [selected, setSelected] = useState<string | null>(null);
  const head = state?.conversation.composition_head;
  const hasPreview = !!head;
  const current =
    state?.run?.approval?.kind === "storyboard" &&
    state.run.approval.decision === "pending"
      ? "storyboard"
      : hasPreview && ["preview", "complete"].includes(p?.stage || "preview")
        ? "preview"
        : p?.scenes.some(
              (scene) => scene.video.artifact_id || active(scene.generation),
            )
          ? "scenes"
          : "storyboard";
  const view = selected || current;
  const originalComposition = state?.run?.workflow?.composition_artifact_id;
  const draft = p?.draft.artifact_id;
  return (
    <div className="production-view">
      <header className="production-heading">
        <nav aria-label="Video stages">
          {[
            ["storyboard", "Storyboard"],
            ["scenes", "Scenes"],
            ["preview", "Preview"],
          ].map(([id, text]) => (
            <button
              key={id}
              aria-pressed={view === id}
              disabled={id === "preview" && !hasPreview}
              onClick={() => setSelected(id)}
            >
              {text}
            </button>
          ))}
        </nav>
        <span>{p?.scenes.length || 0} scenes</span>
        {selected && selected !== current && (
          <button className="chat-button" onClick={() => setSelected(null)}>
            Return to current step
          </button>
        )}
      </header>
      {!p?.storyboard && !head ? (
        <div className="workspace-pending">
          <Sparkles size={28} />
          <h2>Let’s shape your story</h2>
          <p>
            Your storyboard will appear here. Review it before creating your
            video.
          </p>
        </div>
      ) : view === "preview" && head ? (
        <section className="combined-preview" aria-label="Combined video">
          <h2>Your video</h2>
          {draft && head === originalComposition ? (
            <PrivateMedia
              projectId={w.projectId}
              artifactId={draft}
              title="Combined video preview"
            />
          ) : (
            <CompositionPreview
              projectId={w.projectId}
              artifactId={head}
              independent
            />
          )}
          <div className="chat-card-actions">
            <button
              className="chat-button"
              disabled={!w.head || w.head !== head}
              onClick={onEdit}
            >
              Edit
            </button>
            <button
              className="chat-button primary"
              disabled={busy}
              onClick={onExport}
            >
              {pendingPreview ? "Approve and export" : "Export video"}
            </button>
            <button className="chat-button" onClick={() => onRevise()}>
              Request a change
            </button>
          </div>
          {p?.export.status === "queued" || p?.export.status === "running" ? (
            <p role="status">Exporting your approved video…</p>
          ) : null}
        </section>
      ) : (
        <>
          <div className="scene-grid">
            {p?.scenes.map((scene, i) => {
              const step =
                view === "scenes"
                  ? scene.video.artifact_id
                    ? scene.video
                    : scene.generation
                  : scene.frame;
              return (
                <article className="scene-card" key={scene.id}>
                  <div className="scene-card-media">
                    <span className="scene-card-badge">
                      {view === "scenes" ? "SCENE" : "FRAME"}{" "}
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="scene-card-duration">
                      {scene.editorial_duration_seconds}s
                    </span>
                    {step.artifact_id ? (
                      <PrivateMedia
                        projectId={w.projectId}
                        artifactId={step.artifact_id}
                        image={view !== "scenes"}
                        title={
                          view === "scenes"
                            ? `Preview ${scene.id}`
                            : scene.objective
                        }
                      />
                    ) : (
                      <div className="scene-placeholder">
                        <Clapperboard size={26} />
                        <span>{label(step)}</span>
                      </div>
                    )}
                  </div>
                  <h3>
                    {String(i + 1).padStart(2, "0")} {scene.objective}
                  </h3>
                  <p>
                    {view === "storyboard"
                      ? scene.visual_prompt
                      : scene.exact_copy.join(" · ")}
                  </p>
                  <small>{label(step)}</small>
                  {step.error && (
                    <p className="chat-error" role="alert">
                      {step.error.message}
                    </p>
                  )}
                  <button
                    className="chat-button"
                    onClick={() => onRevise(scene.id)}
                  >
                    Revise scene
                  </button>
                </article>
              );
            })}
          </div>
          {p?.music.artifact_id && (
            <section className="production-music">
              <h3>Music</h3>
              <AuthenticatedAudio artifactId={p.music.artifact_id} />
            </section>
          )}
          {p?.storyboard && (
            <section className="production-captions">
              <h3>On-screen copy</h3>
              {p.scenes.map((scene) => (
                <span key={scene.id}>
                  {scene.exact_copy.join(" · ") || "No captions"}
                </span>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function AuthenticatedAudio({ artifactId }: { artifactId: string }) {
  // The shared player uses authenticated loading and the same playback ownership as video.
  return <AudioPreview artifactId={artifactId} />;
}
import { useEffect, useRef } from "react";
import { acquireMedia } from "../lib/media-cache";
import { claimPlayback } from "./private-media";
function AudioPreview({ artifactId }: { artifactId: string }) {
  const w = useWorkspace(),
    audio = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState(""),
    [error, setError] = useState(""),
    [wave, setWave] = useState<number[]>([]);
  useEffect(() => {
    let active = true;
    setUrl(""); setError(""); setWave([]);
    const media = acquireMedia(w.projectId, artifactId);
    void media.ready.then(({ url }) => active && setUrl(url)).catch(e => active && setError(e.message));
    void media.waveform().then(wave => active && setWave(wave)).catch(() => {});
    return () => { active = false; audio.current?.pause(); media.release(); };
  }, [w.projectId, artifactId]);
  useEffect(() => {
    const pause = (event: Event) => {
      if ((event as CustomEvent).detail !== audio.current)
        audio.current?.pause();
    };
    window.addEventListener("vibeshorts:play", pause);
    return () => window.removeEventListener("vibeshorts:play", pause);
  }, []);
  return (
    <>
      {error ? (
        <p role="alert">{error}</p>
      ) : url ? (
        <audio
          ref={audio}
          aria-label="Music preview"
          src={url}
          controls
          onPlay={() => audio.current && claimPlayback(audio.current)}
        />
      ) : (
        <p>Loading music…</p>
      )}
      {wave.length > 0 && (
        <div className="audio-waveform" aria-hidden="true">
          {wave.map((value, i) => (
            <i key={i} style={{ height: Math.max(2, value * 56) }} />
          ))}
        </div>
      )}
    </>
  );
}
