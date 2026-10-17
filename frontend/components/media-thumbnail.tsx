"use client";
import { useEffect, useState } from "react";
import { acquireMedia } from "../lib/media-cache";
import { useVisible } from "../lib/use-visible";

export function MediaThumbnail({ projectId, artifactId, kind, sourceIn = 0, title }: {
  projectId: string; artifactId: string; kind: string; sourceIn?: number; title: string;
}) {
  const [image, setImage] = useState("");
  const { ref, visible } = useVisible<HTMLSpanElement>();
  useEffect(() => {
    setImage("");
    if (!visible) return;
    let active = true;
    const media = acquireMedia(projectId, artifactId);
    void media.thumbnail(kind, sourceIn).then(url => active && setImage(url)).catch(() => {});
    return () => { active = false; media.release(); };
  }, [projectId, artifactId, kind, sourceIn, visible]);
  return <span ref={ref} className="actual-thumbnail" role="img" aria-label={title}
    style={image ? { backgroundImage: `url("${image}")` } : undefined} />;
}
