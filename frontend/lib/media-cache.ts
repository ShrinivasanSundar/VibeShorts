import { firebaseAuth } from "./firebase";
import { ApiError, request } from "./api";

type Media = { blob: Blob; url: string };
type Entry = { refs: number; bytes: number; touched: number; abort: AbortController;
  ready: Promise<Media>; value?: Media; timer?: ReturnType<typeof setTimeout>; wave?: Promise<number[]>;
  thumbnails: Map<string, Promise<string>> };
const entries = new Map<string, Entry>();
const maxBytes = 64 * 1024 * 1024, maxEntries = 20, expiry = 5 * 60 * 1000;

function remove(key: string, entry: Entry) {
  if (entries.get(key) !== entry) return;
  entries.delete(key);
  clearTimeout(entry.timer);
  entry.abort.abort();
  if (entry.value) URL.revokeObjectURL(entry.value.url);
}
function prune() {
  let bytes = [...entries.values()].reduce((total, entry) => total + entry.bytes, 0);
  for (const [key, entry] of [...entries].sort((a, b) => a[1].touched - b[1].touched)) {
    if (bytes <= maxBytes && entries.size <= maxEntries) break;
    if (!entry.refs) { bytes -= entry.bytes; remove(key, entry); }
  }
}
export function clearMediaCache() {
  for (const [key, entry] of entries) remove(key, entry);
}
export function acquireMedia(projectId: string, artifactId: string) {
  const uid = firebaseAuth().currentUser?.uid;
  if (!uid) throw new Error("Sign in to continue.");
  // Artifact IDs are immutable; the API verifies the artifact's content hash.
  const key = JSON.stringify([uid, projectId, artifactId]);
  let entry = entries.get(key);
  if (!entry) {
    const abort = new AbortController();
    entry = { refs: 0, bytes: 0, touched: Date.now(), abort, ready: undefined!, thumbnails: new Map() };
    const current = entry;
    entry.ready = request(`/v1/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(artifactId)}/content`, { signal: abort.signal })
      .then(response => response.blob()).then(blob => {
        if (abort.signal.aborted || entries.get(key) !== current) throw new DOMException("Aborted", "AbortError");
        const value = { blob, url: URL.createObjectURL(blob) };
        current.value = value; current.bytes = blob.size; prune();
        return value;
      }).catch(error => {
        remove(key, current);
        if (error instanceof ApiError && [401, 403].includes(error.status)) clearMediaCache();
        throw error;
      });
    entries.set(key, entry);
  }
  clearTimeout(entry.timer);
  entry.refs++; entry.touched = Date.now();
  const current = entry;
  let released = false;
  return {
    ready: current.ready,
    waveform: () => current.wave ||= current.ready.then(async ({ blob }) => {
      const context = new AudioContext();
      try {
        const audio = await context.decodeAudioData(await blob.arrayBuffer());
        const samples = audio.getChannelData(0), chunk = Math.max(1, Math.floor(samples.length / 100));
        return Array.from({ length: 100 }, (_, i) => {
          let peak = 0;
          for (let j = i * chunk; j < Math.min(samples.length, (i + 1) * chunk); j++) peak = Math.max(peak, Math.abs(samples[j]));
          return peak;
        });
      } finally { await context.close(); }
    }),
    thumbnail: (kind: string, sourceIn: number) => {
      const sample = `${kind}:${sourceIn}`;
      if (!current.thumbnails.has(sample)) current.thumbnails.set(sample, current.ready.then(({ url }) => {
        if (kind === "image") return url;
        return new Promise<string>((resolve, reject) => {
          const video = document.createElement("video");
          let finished = false;
          const cleanup = () => { clearTimeout(timeout); video.onloadeddata = video.onseeked = video.onerror = null; video.removeAttribute("src"); video.load(); };
          const fail = () => { if (!finished) { finished = true; cleanup(); reject(new Error("Thumbnail unavailable")); } };
          const timeout = setTimeout(fail, 15000);
          const capture = () => {
            if (finished || !video.videoWidth) return;
            finished = true;
            const canvas = document.createElement("canvas");
            canvas.width = 120; canvas.height = Math.round(120 * video.videoHeight / video.videoWidth);
            canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.65)); cleanup();
          };
          video.muted = true; video.preload = "auto";
          video.onloadeddata = () => sourceIn > 0 ? video.currentTime = Math.max(0, Math.min(sourceIn, video.duration - 0.01)) : capture();
          video.onseeked = capture; video.onerror = fail; video.src = url;
        });
      }));
      return current.thumbnails.get(sample)!;
    },
    release: () => {
      if (released) return;
      released = true; current.refs--; current.touched = Date.now();
      if (!current.refs) {
        if (!current.value) remove(key, current);
        else { current.timer = setTimeout(() => remove(key, current), expiry); prune(); }
      }
    },
  };
}
