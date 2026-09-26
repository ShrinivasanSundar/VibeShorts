"""Unified Ingest Pipeline.

Coordinates deterministic scene detection, audio clocking, vision tracking,
and semantic labeling to produce a complete FootageIndex cached by SHA-256.
"""

import json
from pathlib import Path
from typing import List, Optional
from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import FootageIndex, Shot
from src.services.ingest.scene_detector import SceneDetector
from src.services.ingest.audio_clock import AudioClockService
from src.services.ingest.vision_tracker import VisionTracker
from src.services.ingest.semantic_labeler import SemanticLabeler


class IngestPipeline:
    """End-to-end deterministic media ingest orchestrator."""

    def __init__(self):
        self.scene_detector = SceneDetector()
        self.audio_clock = AudioClockService()
        self.vision_tracker = VisionTracker()
        self.semantic_labeler = SemanticLabeler()
        self.cache_dir = settings.STORAGE_DIR / "cache" / "footage_indexes"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def process_project_footage(self, project_id: str, media_paths: List[Path]) -> FootageIndex:
        """Ingests raw media files and builds a comprehensive FootageIndex."""
        logger.info(f"Starting deterministic ingest for project={project_id} across {len(media_paths)} files")
        all_shots: List[Shot] = []
        total_duration = 0.0

        for media_path in media_paths:
            shots = self._ingest_file(project_id, media_path)
            all_shots.extend(shots)
            for s in shots:
                total_duration += s.duration

        footage_index = FootageIndex(
            project_id=project_id,
            shots=all_shots,
            audio_tracks=[],
            total_raw_duration=round(total_duration, 2)
        )

        # Cache project index
        cache_file = self.cache_dir / f"{project_id}_index.json"
        with open(cache_file, "w") as f:
            f.write(footage_index.model_dump_json(indent=2))

        logger.info(f"Ingest complete: {len(all_shots)} shots indexed for project {project_id}")
        return footage_index

    def _ingest_file(self, project_id: str, media_path: Path) -> List[Shot]:
        """Ingests a single media file, checking hash cache first."""
        file_hash = self.scene_detector.compute_sha256(media_path)
        file_cache = self.cache_dir / f"{file_hash}.json"

        if file_cache.exists():
            logger.info(f"Loading cached shots for hash={file_hash} ({media_path.name})")
            try:
                with open(file_cache, "r") as f:
                    data = json.load(f)
                    return [Shot(**item) for item in data]
            except Exception as e:
                logger.warning(f"Failed reading cache for {file_hash}: {e}")

        scenes = self.scene_detector.detect_scenes(media_path)
        shots: List[Shot] = []

        for idx, (start_sec, end_sec) in enumerate(scenes):
            duration = round(end_sec - start_sec, 3)
            shot_id = f"{media_path.stem}_shot_{idx+1:03d}"

            # 1. Extract audio & transcribe with Speech-to-Text
            wav_path = settings.TEMP_DIR / f"{shot_id}.wav"
            try:
                self.audio_clock.extract_audio_segment(media_path, start_sec, duration, wav_path)
                transcript, words = self.audio_clock.transcribe_with_timestamps(wav_path)
                loudness = self.audio_clock.measure_loudness_lufs(wav_path)
            except Exception as e:
                logger.error(f"Audio processing error on {shot_id}: {e}")
                transcript, words, loudness = "", [], -24.0

            has_speech = len(words) > 0

            # 2. Extract keyframe & compute 9:16 crop focus
            keyframe_path = settings.TEMP_DIR / f"{shot_id}_keyframe.jpg"
            midpoint = start_sec + (duration / 2.0)
            try:
                self.vision_tracker.extract_keyframe(media_path, midpoint, keyframe_path)
                focus_x, focus_y = self.vision_tracker.detect_subject_focus(keyframe_path)
                crop_box = self.vision_tracker.compute_9_16_crop_box(media_path, focus_x, focus_y)
            except Exception as e:
                logger.error(f"Vision tracking error on {shot_id}: {e}")
                crop_box = None

            # 3. Semantic shot labeling with Gemini
            roll_type, description = self.semantic_labeler.label_shot(keyframe_path, transcript, has_speech)

            shot = Shot(
                shot_id=shot_id,
                source_file_uri=str(media_path.resolve()),
                sha256_hash=file_hash,
                start_time=round(start_sec, 3),
                end_time=round(end_sec, 3),
                duration=duration,
                roll_type=roll_type,
                semantic_description=description,
                transcript=transcript,
                words=words,
                average_loudness_lufs=loudness,
                primary_focus_box=crop_box,
                has_speech=has_speech
            )
            shots.append(shot)

        # Cache shots for this file hash
        with open(file_cache, "w") as f:
            f.write(json.dumps([s.model_dump() for s in shots], indent=2))

        return shots
