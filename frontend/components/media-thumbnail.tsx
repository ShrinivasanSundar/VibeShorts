"use client";
import { useEffect, useState } from "react";
import { request } from "../lib/api";
import { projectRoot } from "../lib/workspace";

// Sample the actual asset locally; never play it or acquire editor playback ownership.
export function MediaThumbnail({
  projectId,
  artifactId,
  kind,
  sourceIn = 0,
  title,
}: {
  projectId: string;
  artifactId: string;
  kind: string;
  sourceIn?: number;
  title: string;
}) {
  const [image, setImage] = useState("");
  useEffect(() => {
    let active = true,
      object = "",
      video: HTMLVideoElement | undefined;
    const abort = new AbortController();
    setImage("");
    void request(`${projectRoot(projectId)}/assets/${artifactId}/content`, {
      signal: abort.signal,
    })
      .then((r) => r.blob())
      .then((blob) => {
        object = URL.createObjectURL(blob);
        if (!active) {
          URL.revokeObjectURL(object);
          return;
        }
        if (kind === "image") {
          setImage(object);
          return;
        }
        video = document.createElement("video");
        video.muted = true;
        video.preload = "auto";
        const capture = () => {
          if (!active || !video?.videoWidth) return;
          const canvas = document.createElement("canvas");
          canvas.width = 120;
          canvas.height = Math.round(
            (120 * video.videoHeight) / video.videoWidth,
          );
          canvas
            .getContext("2d")
            ?.drawImage(video, 0, 0, canvas.width, canvas.height);
          setImage(canvas.toDataURL("image/jpeg", 0.65));
          video.removeAttribute("src");
          video.load();
        };
        video.onloadeddata = () => {
          if (sourceIn > 0)
            video!.currentTime = Math.min(sourceIn, video!.duration - 0.01);
          else capture();
        };
        video.onseeked = capture;
        video.src = object;
      })
      .catch(() => {
        /* Asset remains selectable when a thumbnail cannot be decoded. */
      });
    return () => {
      active = false;
      abort.abort();
      if (video) {
        video.onloadeddata = null;
        video.onseeked = null;
        video.removeAttribute("src");
        video.load();
      }
      if (object) URL.revokeObjectURL(object);
    };
  }, [projectId, artifactId, kind, sourceIn]);
  return image ? (
    <span
      className="actual-thumbnail"
      role="img"
      aria-label={title}
      style={{ backgroundImage: `url("${image}")` }}
    />
  ) : null;
}
