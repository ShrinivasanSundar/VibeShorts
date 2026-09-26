"""Vision Tracker & Dynamic 9:16 Re-framing Saliency.

Detects faces and key subjects on shot keyframes to anchor the 9:16 vertical crop window.
Ensures subjects remain centered while respecting safe zones.
"""

import subprocess
from pathlib import Path
from typing import Optional, Tuple
from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import BoundingBox


class VisionTracker:
    """Calculates saliency and subject-anchored 9:16 crop bounding boxes."""

    def extract_keyframe(self, video_path: Path, timestamp_sec: float, output_jpg: Path) -> Path:
        """Extracts a single keyframe JPEG from the video at timestamp_sec."""
        output_jpg.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-ss", str(timestamp_sec),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_jpg)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_jpg

    def get_video_dimensions(self, video_path: Path) -> Tuple[int, int]:
        """Returns (width, height) of the video."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            w, h = res.stdout.strip().split("x")
            return int(w), int(h)
        except Exception:
            return 1920, 1080

    def compute_9_16_crop_box(
        self,
        video_path: Path,
        focus_center_x: float = 0.5,
        focus_center_y: float = 0.5
    ) -> BoundingBox:
        """Calculates normalized (ymin, xmin, ymax, xmax) for a 9:16 vertical crop.

        For 16:9 input (1920x1080):
        The 9:16 crop height is the full height (1080).
        The required width is 1080 * (9/16) = 607.5 pixels.
        Normalized crop width = 607.5 / 1920 = 0.3164.
        """
        src_w, src_h = self.get_video_dimensions(video_path)
        target_aspect = 9.0 / 16.0
        src_aspect = src_w / src_h

        if src_aspect >= target_aspect:
            # Source is wider than 9:16 (standard landscape or 1:1)
            crop_width_norm = (src_h * target_aspect) / src_w
            half_w = crop_width_norm / 2.0

            xmin = max(0.0, min(focus_center_x - half_w, 1.0 - crop_width_norm))
            xmax = xmin + crop_width_norm

            return BoundingBox(ymin=0.0, xmin=round(xmin, 4), ymax=1.0, xmax=round(xmax, 4))
        else:
            # Source is narrower than 9:16 (rare)
            crop_height_norm = (src_w / target_aspect) / src_h
            half_h = crop_height_norm / 2.0

            ymin = max(0.0, min(focus_center_y - half_h, 1.0 - crop_height_norm))
            ymax = ymin + crop_height_norm

            return BoundingBox(ymin=round(ymin, 4), xmin=0.0, ymax=round(ymax, 4), xmax=1.0)

    def detect_subject_focus(self, keyframe_path: Path) -> Tuple[float, float]:
        """Detects subject center (x, y) in normalized [0.0, 1.0] coordinates.

        Attempts MediaPipe face detection; defaults to center (0.5, 0.5) if not detected.
        """
        try:
            import cv2
            import mediapipe as mp

            image = cv2.imread(str(keyframe_path))
            if image is None:
                return 0.5, 0.5

            h, w, _ = image.shape
            mp_face_detection = mp.solutions.face_detection
            with mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5) as face_detector:
                results = face_detector.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                if results.detections:
                    # Pick detection with largest bounding box
                    best_detection = max(
                        results.detections,
                        key=lambda d: d.location_data.relative_bounding_box.width * d.location_data.relative_bounding_box.height
                    )
                    bb = best_detection.location_data.relative_bounding_box
                    center_x = bb.xmin + (bb.width / 2.0)
                    center_y = bb.ymin + (bb.height / 2.0)
                    return round(center_x, 3), round(center_y, 3)
        except Exception as e:
            logger.debug(f"MediaPipe detection skipped or unavailable ({e}); defaulting focus to center (0.5, 0.5)")

        return 0.5, 0.5
