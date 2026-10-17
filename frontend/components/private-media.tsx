"use client";

import { useEffect, useRef, useState } from "react";
import { request } from "../lib/api";
import { projectRoot } from "../lib/workspace";
import { Reel } from "./loading-state";
import { acquireMedia } from "../lib/media-cache";
import { useVisible } from "../lib/use-visible";


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
  const { ref: loadingRef, visible } = useVisible<HTMLDivElement>();
  useEffect(() => {
    setUrl(""); setError("");
    if (!visible) return;
    let active = true;
    const media = acquireMedia(projectId, artifactId);
    void media.ready.then(({ url }) => active && setUrl(url)).catch(e => active && setError(e.message));
    return () => { active = false; video.current?.pause(); media.release(); };
  }, [projectId, artifactId, visible]);
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
      <div ref={loadingRef} className="chat-media-loading" role="status">
        Loading preview…
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
