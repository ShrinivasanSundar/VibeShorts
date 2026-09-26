"""ASS (Advanced SubStation Alpha) Subtitle Generator.

Compiles Speech-to-Text word timestamps into kinetic, TikTok/Reels-style burned subtitles.
Shifts source word timestamps onto the output timeline and bounds them strictly inside the safe zone.
"""

from pathlib import Path
from typing import List
from src.models.schemas import EditPlan, FootageIndex, Shot, WordTimestamp


class ASSCaptionGenerator:
    """Generates styled ASS subtitle files for FFmpeg rendering."""

    ASS_HEADER_TEMPLATE = """[Script Info]
Title: VibeShorts Dynamic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,450,1
Style: Highlight,Montserrat,74,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Converts seconds into ASS timestamp format: H:MM:SS.cs"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int(round((seconds - int(seconds)) * 100))
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def generate_ass_file(self, plan: EditPlan, index: FootageIndex, output_path: Path) -> Path:
        """Generates an ASS subtitle file from an EditPlan and FootageIndex."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shots_by_id = {s.shot_id: s for s in index.shots}

        events: List[str] = []
        timeline_offset = 0.0

        for cut in plan.cuts:
            shot = shots_by_id.get(cut.shot_id)
            if not shot or not shot.words:
                timeline_offset += cut.timeline_duration
                continue

            # Filter words strictly inside the cut's snapped [in_point, out_point]
            cut_words = [
                w for w in shot.words
                if w.end >= cut.in_point_sec and w.start <= cut.out_point_sec
            ]

            # Group words into short punchy chunks of 2-3 words for high viewer engagement
            chunk_size = 3
            for i in range(0, len(cut_words), chunk_size):
                chunk = cut_words[i:i + chunk_size]
                if not chunk:
                    continue

                chunk_start = timeline_offset + max(0.0, chunk[0].start - cut.in_point_sec)
                chunk_end = timeline_offset + min(cut.timeline_duration, chunk[-1].end - cut.in_point_sec + 0.1)

                start_str = self._format_timestamp(chunk_start)
                end_str = self._format_timestamp(chunk_end)
                caption_text = " ".join([w.word.upper() for w in chunk])

                # Dialogue event centered in safe margin
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{caption_text}")

            timeline_offset += cut.timeline_duration

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.ASS_HEADER_TEMPLATE)
            f.write("\n".join(events))
            f.write("\n")

        return output_path
