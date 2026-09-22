"""Google Cloud Speech-to-Text for voice-driven editing."""

from __future__ import annotations

import os
from pathlib import Path

from vibeshorts.config import VibeShortsConfig


class SpeechClient:
    def __init__(self, config: VibeShortsConfig):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.config.integrations.enable_speech:
                raise RuntimeError("Speech integration is disabled in config")
            from google.cloud import speech

            self._client = speech.SpeechClient()
        return self._client

    def transcribe_file(self, audio_path: Path, language_code: str = "en-US") -> str:
        from google.cloud import speech

        client = self._get_client()
        with audio_path.open("rb") as f:
            content = f.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code=language_code,
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)
        return " ".join(result.alternatives[0].transcript for result in response.results)

    def transcribe_gcs(self, gcs_uri: str, language_code: str = "en-US") -> str:
        from google.cloud import speech

        client = self._get_client()
        audio = speech.RecognitionAudio(uri=gcs_uri)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            language_code=language_code,
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)
        return " ".join(result.alternatives[0].transcript for result in response.results)
