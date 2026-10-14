"use client";
import { useEffect, useState } from "react";
import { request } from "../lib/api";
import { useWorkspace } from "../lib/workspace";

export function AudioWaveform({ artifactId }: { artifactId: string }) {
  const w = useWorkspace();
  const [values, setValues] = useState<number[]>([]);
  useEffect(() => {
    const abort = new AbortController();
    let active = true;
    let context: AudioContext | undefined;
    setValues([]);
    void request(`${w.base}/assets/${artifactId}/content`, {
      signal: abort.signal,
    })
      .then((r) => r.arrayBuffer())
      .then(async (data) => {
        if (!active) return;
        context = new AudioContext();
        const audio = await context.decodeAudioData(data);
        const samples = audio.getChannelData(0);
        const chunk = Math.max(1, Math.floor(samples.length / 100));
        const peaks = Array.from({ length: 100 }, (_, i) => {
          let peak = 0;
          for (
            let j = i * chunk;
            j < Math.min(samples.length, (i + 1) * chunk);
            j++
          )
            peak = Math.max(peak, Math.abs(samples[j]));
          return peak;
        });
        if (active) setValues(peaks);
      })
      .catch(() => {
        /* Keep the audio clip editable if decoding is unavailable. */
      })
      .finally(() => {
        void context?.close();
      });
    return () => {
      active = false;
      abort.abort();
    };
  }, [w.base, artifactId]);
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
