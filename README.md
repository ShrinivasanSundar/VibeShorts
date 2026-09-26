
VibeShorts, an autonomous AI video editing system built with **Google Gemini** (via Google AntiGravity SDK), **Google Cloud Speech-to-Text**, Vertex AI for Veo, Omni, Lyria, and **FFmpeg**.

---

## 1. Executive Summary

VibeShorts automates short-form video creation (such as TikTok, Instagram Reels, and DTC video ads). 

It accepts:
1. A folder of raw, unstructured video clips (A-roll talking heads, B-roll product shots).
2. A structured creative brief (target product, audience, tone, duration) - Idea from users and changes in the video.

It processes this through an **ensemble of AI agents**. Ingest writes a deterministic clock, the Director plans the story, FFmpeg executes the frame, and the Reviewer returns a short patch list.

```
Raw Footage + Creative Brief
            │
            ▼
   [ 1. Ingest ]                Scene cuts, voice activity, loudness, face / product boxes
            │                   Google Speech-to-Text: transcript + word timestamps
            │                   Gemini labels each short shot (what is shown, A-roll or B-roll).
            │                   Gemini does not own the timestamps.
            │                   Outputs: FootageIndex of shots, cached by file hash
            ▼
   [ 2. Director Agent ]        Gemini AntiGravity SDK
            │                   Searches FootageIndex & writes a structured EditPlan
            │                   Each entry: source shot, in/out, 9:16 crop,
            │                   caption-safe region, music and ducking cues
            ▼
   [ 3. Trim Refiner ]          Snaps IN/OUT to the nearest word or pause on the audio index
            │                   Gemini probe only when the semantic edge is ambiguous
            ▼
   [ 4. Editor (Executor) ]     FFmpeg
            │                   Cuts, reframes to 9:16, burns ASS inside the safe region,
            │                   mixes audio from the plan's music and ducking cues
            ▼
   [ 5. Reviewer Agent ]        Gemini watches the rendered MP4
            │                   Returns a patch list: tighten hook, swap shot, reframe
            │
            ├──► Story patches ──────────────► Director (capped retries)
            ├──► Caption / loudness failures ► Editor (not the Director)
            └──► No remaining patches ───────► Exports final video
```

### Backend / Deployment

GCP:

* A bucket for uploaded photos, video footage, and editor results.
* Vertex AI: Veo, Omni, Gemini, and Lyria APIs.
* Google Cloud Speech-to-Text for transcripts and word-level caption timestamps.
* A GCE VM (Container-Optimized OS) that runs the backend and serves the frontend. FFmpeg renders and Gemini calls stay on the VM. They outlive a workflow job.

Frontend: a Next.js chat on the right, and a video viewer on the left for the edited cut, with upload for photos and footage.

**GitHub Actions deploys the container. It does not run the edit.**

1. **Authenticate with Workload Identity Federation.** GitHub’s OIDC token impersonates a deploy service account. No JSON key in repository secrets.
2. **Build and push** the backend and Next.js image to Artifact Registry on each push to `main`.
3. **Update the GCE VM** to that image. The footage bucket stays in place. Vertex, Speech-to-Text, Veo, and Lyria are APIs the VM calls with its own service account.

The deploy service account needs Artifact Registry writer and compute admin on that instance. The runtime service account needs Speech-to-Text, Vertex AI, and object access on the footage bucket.

---

## 2. System Architecture & Core Components

### 1. Ingest writes the clock
Deterministic ingest runs before any agent call. It cuts scenes, detects voice activity, measures loudness, and records face or product boxes. **Google Cloud Speech-to-Text** transcribes each shot and returns a word-level timestamp for every word. Those timestamps drive auto captions and give the Trim Refiner a clock to snap against. Gemini then labels each short shot: what is shown, and whether it is A-roll or B-roll. Speech-to-Text owns the transcript and the timestamps. Gemini does not.

Veo, Omni, and Lyria enter here as a side door. Generated B-roll, stills, and a music bed are indexed like any other asset. They are not a later stage on the reviewer loop.

### 2. Director Agent
Gemini via the AntiGravity SDK searches the `FootageIndex` against the creative brief and writes a structured `EditPlan`. The story order is the Director's job. The clock on each cut comes from the index.

### 3. Trim Refiner
In and out points snap to the nearest word or pause already stored on the shot. A short Gemini probe runs only when the semantic edge is ambiguous (a thought that should end before the silence, a reaction that should hold past the last word). The Director's story order stays intact.

### 4. EditPlan carries the frame
Each `EditPlanEntry` is one cut the Editor can execute without guessing:

* Source shot, with in/out already snapped to a word or pause.
* A 9:16 crop anchored on the face or product box.
* A caption-safe region that stays clear of platform chrome.
* Music and ducking cues, so the mix is specified in the plan.

FFmpeg cuts, reframes, burns TikTok-style ASS captions from the Speech-to-Text word timestamps (shifted onto the output timeline), and mixes from those cues.

### 5. Reviewer patches, then stops
Gemini watches the rendered MP4 and returns a patch list, not a single score: tighten the hook, swap a shot, reframe.

* Story patches go back to the Director. Retries are capped, and each retry edits the previous plan.
* Caption drift and loudness failures stay with the Editor. They are not re-planned as story.
* When the list is empty, or the cap is hit, the video is the final export.

---

## 3. Data Models (`src/models/schemas.py`)

| Schema | Purpose |
| :--- | :--- |
| `CreativeBrief` | Defines `product`, `audience`, `tone`, `duration_seconds`, and optional `style_ref`. |
| `WordTimestamp` | Speech-to-Text `word`, `start`, `end` on the source shot. Captions shift these onto the output timeline. |
| `Shot` | One scene: `source_file`, `start_time`, `end_time`, Speech-to-Text `transcript` and `words`, `roll_type`, loudness, and face or product boxes. Gemini adds what is shown. |
| `FootageIndex` | Catalog of shots, cached by file hash. Includes generated assets from Veo, Omni, and Lyria. |
| `EditPlanEntry` | One cut: source shot, in/out snapped to a word or pause, 9:16 crop, caption-safe region, music and ducking cues, `text_overlay`. |
| `EditPlan` | Ordered blueprint the Editor executes. |
| `ReviewPatch` | One edit: `tighten_hook`, `swap_shot`, or `reframe`, or an Editor-owned caption / loudness fix. Story patches target the Director and stop at the retry cap. |

---

## 4. Key Takeaways for VibeShorts

1. **Ingest owns the clock.** Scene cuts, voice activity, loudness, and face or product boxes are deterministic. Google Cloud Speech-to-Text writes the transcript and the word timestamps used for auto captions. Gemini labels shots. It does not emit timestamps.
2. **The EditPlan carries the frame.** Every entry has a source shot, in/out snapped to a word or pause, a 9:16 crop, a caption-safe region, and music and ducking cues. FFmpeg executes that plan and does not invent framing or mix levels.
3. **The tight pass reads the audio index.** The Trim Refiner snaps to a word or pause already stored on the shot. A Gemini probe runs only when the semantic edge is ambiguous.
4. **The Reviewer patches, then stops.** It returns tighten hook, swap shot, or reframe. Story patches go to the Director with a retry cap. Caption and loudness failures stay with the Editor.

## Future improvements
- Connect to Google Photos 
- Export the video assets to Davinci Resolve and Adobe Premiere