"use client";

import { useEffect, useRef, useState } from "react";
import { request } from "../lib/api";
import { projectRoot } from "../lib/workspace";
import { Reel } from "./loading-state";

// A shared play event also pauses compositions in the editor and historical cards.
export function claimPlayback(owner: object) {
  window.dispatchEvent(new CustomEvent("vibeshorts:play", { detail: owner }));
}

export function PrivateMedia({
  projectId,
  artifactId,
  image = false,
  title = "Scene preview",
}: {
  projectId: string;
  artifactId: string;
  image?: boolean;
  title?: string;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    let active = true;
    let object = "";
    const abort = new AbortController();
    setUrl("");
    setError("");
    void request(
      `${projectRoot(projectId)}/assets/${encodeURIComponent(artifactId)}/content`,
      { signal: abort.signal },
    )
      .then((r) => r.blob())
      .then((blob) => {
        object = URL.createObjectURL(blob);
        if (active) setUrl(object);
        else URL.revokeObjectURL(object);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
      abort.abort();
      video.current?.pause();
      if (object) URL.revokeObjectURL(object);
    };
  }, [projectId, artifactId]);
  useEffect(() => {
    const pause = (event: Event) => {
      if ((event as CustomEvent).detail !== video.current)
        video.current?.pause();
    };
    window.addEventListener("vibeshorts:play", pause);
    return () => window.removeEventListener("vibeshorts:play", pause);
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (!url)
    return (
      <div className="chat-media-loading" role="status">
        <Reel />
        <span>Loading preview…</span>
      </div>
    );
  return image ? (
    <img className="chat-attachment-image" src={url} alt={title} />
  ) : (
    <video
      ref={video}
      className="chat-video"
      src={url}
      controls
      playsInline
      preload="metadata"
      aria-label={title}
      onPlay={() => video.current && claimPlayback(video.current)}
    />
  );
}
