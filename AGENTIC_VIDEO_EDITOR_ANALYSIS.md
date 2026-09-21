# Architecture & Implementation Analysis: `poseljacob/agentic-video-editor`

A deep-dive technical analysis of the open-source repository [poseljacob/agentic-video-editor](https://github.com/poseljacob/agentic-video-editor), an autonomous AI video editing system built with **Google Gemini** (via Google Agent Development Kit / ADK) and **FFmpeg**.

---

## 1. Executive Summary

`agentic-video-editor` (CLI tool `ave`) automates short-form video creation (such as TikTok, Instagram Reels, and DTC video ads). It accepts:
1. A folder of raw, unstructured video clips (A-roll talking heads, B-roll product shots).
2. A structured creative brief (target product, audience, tone, duration).

It processes this through an **ensemble of AI agents** orchestrating scene detection, shot indexing, narrative sequencing, frame-accurate trimming, automated video rendering with kinetic subtitles, and an automated quality evaluation feedback loop.

```
Raw Footage + Creative Brief
            │
            ▼
   [ 1. Preprocessing ]         PySceneDetect (shot cuts) + Faster-Whisper (word timestamps)
            │                   Outputs: FootageIndex JSON (A-roll, B-roll, metadata)
            ▼
   [ 2. Director Agent ]        Gemini 3.1 Pro via Google ADK
            │                   Searches FootageIndex & generates structured EditPlan
            ▼
   [ 3. Trim Refiner ]          Parallel short-clip probes (~6s) to Gemini
            │                   Snaps IN/OUT points to frame-accurate speech/pause boundaries
            ▼
   [ 4. Editor (Executor) ]     FFmpeg / MoviePy / pysubs2
            │                   Cuts clips, generates TikTok-style ASS captions, mixes audio
            ▼
   [ 5. Reviewer Agent ]        Gemini native video understanding watches the rendered MP4
            │                   Scores (0-1): adherence, pacing, visual quality, watchability
            │
            ├──► If score < threshold (e.g. 0.65) ──► Feeds critique back to Director (Retries)
            └──► If score >= threshold ─────────────► Exports final video
```

---

## 2. System Architecture & Core Components

### A. Preprocessing Pipeline (`src/pipeline/preprocess.py`)
Deterministic preprocessing runs **before** calling LLMs to extract structural and lexical metadata from the media assets:
* **Scene Transition Detection (`PySceneDetect`):** Splits long raw camera files into individual continuous shots (`Shot` schema).
* **Speech-to-Text & Word Timestamps (`Faster-Whisper`):** Generates full transcripts with exact start and end timestamps for *every individual word* (`WordTimestamp`).
* **Shot Classification (Roll Type):** Automatically detects `a-roll` (on-camera talent / talking head) and `b-roll` (cutaways, environment, product texture) based on directory naming or visual cues.
* **Footage Index Generation:** Emits a serialized `FootageIndex` (JSON) containing all shots, durations, word timestamps, and roll types.

---

### B. The Director Agent (`src/agents/director.py`)
The creative orchestrator responsible for narrative and pacing:
* **Engine:** Built with **Google ADK (`google.adk.agents.Agent`)** powered by `gemini-3.1-pro`.
* **Tools:**
  * `search_moments`: Fast local lexical search over the pre-built `FootageIndex` (finds relevant dialogue, phrases, or topics).
  * `analyze_footage`: Deep multimodal video inspection using Gemini File API for candidate clips.
* **Style Schemas & Templates (`styles/*.yaml`):** Implements structured ad arcs (e.g. `dtc-testimonial.yaml`):
  * **0:00 - 0:03:** Hook (high-energy visual / problem statement).
  * **0:03 - 0:10:** Problem explanation.
  * **0:10 - 0:20:** Solution showcase with B-roll cutaway.
  * **0:20 - 0:27:** Social proof / customer testimony.
  * **0:27 - 0:30:** Call to Action (CTA).
* **Strict Contract:** Outputs a Pydantic `EditPlan` specifying ordered entries with shot IDs (`{source_file}#{start_time}`), initial trims, overlays, and transitions.

---

### C. Trim Refiner Agent (`src/agents/trim_refiner.py`)
Addresses the known limitation of LLM timestamp drift over long video contexts:
* **The Problem:** LLMs analyzing long videos produce approximate cuts (e.g., cutting at `00:12.0` instead of `00:12.4`, cutting off the first syllable of a word).
* **Two-Pass Solution:** The Trim Refiner extracts **~6-second probe clips** centered around each proposed `start_trim` and `end_trim`.
* **Parallel Processing:** Dispatches probe clips to Gemini in parallel (`ThreadPoolExecutor`, max 6 workers) asking Gemini to detect exact visual and audio pause boundaries.
* **Refined Output:** Returns an updated `EditPlan` with frame-tight cuts without disturbing the Director's story structure.

---

### D. The Editor Execution Engine (`src/agents/editor.py` & `src/tools/`)
A deterministic execution agent that takes the `EditPlan` and executes rendering without making creative decisions:
* **Fast Sub-clip Extraction (`src/tools/edit.py`):** Uses FFmpeg stream copy for speed and lossless intermediate cuts.
* **Animated Kinetic Captions (`src/tools/captions.py`):**
  * Utilizes `pysubs2` to build Advanced SubStation Alpha (`.ass`) subtitles.
  * Uses the per-word timestamps from Faster-Whisper to implement TikTok/Reels-style karaoke animations (highlighting words in vivid colors, e.g., `#4ACFFF`, as they are spoken).
  * Burns subtitles directly onto the video stream using FFmpeg’s `ass` video filter.
* **Clip Sequencing & Assembly:** Concatenates trimmed and captioned segments in order using FFmpeg's concat demuxer.
* **Audio Mastering & Ducking:** Mixes background music under voice tracks, lowering music volume when speech is active.
* **Final Export (`src/tools/render.py`):** Renders vertical 9:16 (1080x1920) or horizontal H.264 MP4.

---

### E. The Reviewer & Self-Correction Feedback Loop (`src/agents/reviewer.py` & `src/pipeline/runner.py`)
An automated Quality Assurance (QA) cycle:
* **Reviewer Agent:** Takes the rendered MP4 video and original creative brief, uploading the video to Gemini multimodal understanding.
* **Evaluation Metrics (0.0 to 1.0):**
  1. `adherence`: Match with product, audience, and tone.
  2. `pacing`: Hook strength, cut rhythm, energy progression.
  3. `visual_quality`: Framing, color grading, readability.
  4. `watchability`: Likelihood of retaining viewers to the end.
  5. `overall`: Weighted holistic evaluation.
* **Actionable Feedback:** If `overall < 0.7`, the reviewer must provide timestamped, prescriptive critique (e.g., *"Clip 1 hook dragged; swap with high-energy product shot at 0:15"*).
* **Declarative Retries (`pipelines/ugc-ad.yaml`):**
  ```yaml
  steps:
    - agent: director
    - agent: trim_refiner
    - agent: editor
    - agent: reviewer
      retry_if:
        metric: overall
        threshold: 0.65
        max_retries: 2
        feedback_target: director
  ```
  If the cut fails quality evaluation, reviewer feedback is injected back into the Director prompt, generating `_v1.mp4`, `_v2.mp4`, etc., until quality passes or retries are exhausted.

---

## 3. Data Models (`src/models/schemas.py`)

| Schema | Purpose |
| :--- | :--- |
| `CreativeBrief` | Defines `product`, `audience`, `tone`, `duration_seconds`, and optional `style_ref`. |
| `WordTimestamp` | Stores `word`, `start`, `end` times for kinetic captioning. |
| `Shot` | Represents a scene segment: `source_file`, `start_time`, `end_time`, `transcript`, `words`, `roll_type`. |
| `FootageIndex` | Aggregated catalog of all available shots across the raw media library. |
| `EditPlanEntry` | An individual cut: `shot_id` (`{file}#{start}`), `start_trim`, `end_trim`, `position`, `text_overlay`. |
| `EditPlan` | Complete blueprint for the timeline assembly. |
| `ReviewScore` | Quantitative scores (`adherence`, `pacing`, `visual_quality`, `watchability`, `overall`) + free-form critique. |

---

## 4. Key Takeaways for VibeShorts

1. **Separation of Planning vs. Execution:**  
   LLMs should reason about narratives, timing, and selection, emitting structured JSON (`EditPlan`). The execution engine (FFmpeg, DaVinci Resolve, WebAssembly) handles actual video pixel operations.
2. **Two-Pass Precision Trimming:**  
   Coarse selection over the whole footage pool followed by micro-clip (~6s) Gemini probe analysis eliminates timestamp hallucinations.
3. **Word-Level Subtitles Make or Break Short-Form Video:**  
   Using Whisper per-word timestamps with styled `.ass` files creates native TikTok/Reels kinetic captions without third-party caption services.
4. **Autonomous Self-Correction:**  
   Having a multimodal Reviewer agent watch the rendered export ensures that failed cuts are caught and re-directed automatically before user delivery.
