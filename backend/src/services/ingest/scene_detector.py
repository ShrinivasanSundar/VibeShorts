"""Deterministic Scene Boundary Detection Engine.

Uses Content & Adaptive detection to split raw video into atomic shots.
Computes SHA-256 hash of media file to enable cache-first indexing.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import List, Tuple
from src.core.config import settings
from src.core.logging import logger


class SceneDetector:
    """Detects visual scene transitions deterministically."""

    def __init__(self, threshold: float = 27.0, min_scene_len_sec: float = 1.0):
        self.threshold = threshold
        self.min_scene_len_sec = min_scene_len_sec

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Computes SHA-256 checksum of source media for caching."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def detect_scenes(self, video_path: Path) -> List[Tuple[float, float]]:
        """Splits video into (start_time_sec, end_time_sec) intervals.

        Attempts PySceneDetect first; falls back to FFmpeg scene filter if scenedetect is unavailable.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Media file not found: {video_path}")

        try:
            return self._detect_with_pyscenedetect(video_path)
        except Exception as e:
            logger.warning(f"PySceneDetect detection failed or not installed ({e}); falling back to FFmpeg scene detector.")
            return self._detect_with_ffmpeg(video_path)

    def _detect_with_pyscenedetect(self, video_path: Path) -> List[Tuple[float, float]]:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector, AdaptiveDetector

        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=self.threshold))
        scene_manager.add_detector(AdaptiveDetector())
        scene_manager.detect_scenes(video)

        scene_list = scene_manager.get_scene_list()
        if not scene_list:
            # Entire clip is a single continuous shot
            duration = video.duration.get_seconds()
            return [(0.0, duration)]

        results = []
        for start, end in scene_list:
            start_sec = start.get_seconds()
            end_sec = end.get_seconds()
            if (end_sec - start_sec) >= self.min_scene_len_sec:
                results.append((start_sec, end_sec))

        return results if results else [(0.0, video.duration.get_seconds())]

    def _detect_with_ffmpeg(self, video_path: Path) -> List[Tuple[float, float]]:
        """FFmpeg-based scene transition detection fallback."""
        total_duration = self._get_video_duration(video_path)
        cmd = [
            settings.FFMPEG_PATH,
            "-i", str(video_path),
            "-filter:v", f"select='gt(scene,0.35)',metadata=print:file=-",
            "-f", "null", "-"
        ]
        
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            cut_points = [0.0]
            for line in proc.stderr.splitlines():
                if "pts_time:" in line:
                    parts = line.split("pts_time:")
                    if len(parts) > 1:
                        try:
                            t = float(parts[1].split()[0])
                            if t > cut_points[-1] + self.min_scene_len_sec:
                                cut_points.append(t)
                        except ValueError:
                            pass
            cut_points.append(total_duration)
            
            scenes = []
            for i in range(len(cut_points) - 1):
                start = cut_points[i]
                end = cut_points[i + 1]
                if end - start >= self.min_scene_len_sec:
                    scenes.append((start, end))
            return scenes if scenes else [(0.0, total_duration)]
        except Exception as e:
            logger.error(f"FFmpeg scene detection failed: {e}")
            return [(0.0, total_duration)]

    def _get_video_duration(self, video_path: Path) -> float:
        """Retrieves video duration via ffprobe or ffmpeg."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            return 30.0  # Safe default fallback
