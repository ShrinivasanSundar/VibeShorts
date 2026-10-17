"use client";
import { useEffect, useState } from "react";
import { acquireMedia } from "../lib/media-cache";
import { useWorkspace } from "../lib/workspace";

export function AudioWaveform({ artifactId }: { artifactId: string }) {
  const w = useWorkspace();
  const [values, setValues] = useState<number[]>([]);
  useEffect(() => {
    let active = true;
    setValues([]);
    const media = acquireMedia(w.projectId, artifactId);
    void media.waveform().then(values => active && setValues(values)).catch(() => {});
    return () => { active = false; media.release(); };
  }, [w.projectId, artifactId]);
  if (!values.length) return null;
  const peak = Math.max(...values, 0.001);
  return (
    <svg
      className="actual-waveform"
      viewBox="0 0 400 60"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {values.map((value, i) => {
        const height = Math.max(1, (value / peak) * 50);
        return (
          <rect
            key={i}
            x={i * 4}
            y={(60 - height) / 2}
            width="2"
            height={height}
            rx="1"
            fill="currentColor"
          />
        );
      })}
    </svg>
  );
}
