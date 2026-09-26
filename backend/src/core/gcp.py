"""Google Cloud Platform client factories and abstractions."""

from typing import Optional
from src.core.config import settings
from src.core.logging import logger

try:
    from google.auth.exceptions import DefaultCredentialsError
except ImportError:
    DefaultCredentialsError = Exception


class GCPClientManager:
    """Manages GCP client singletons with graceful local/offline fallback."""

    _instance: Optional["GCPClientManager"] = None

    def __init__(self):
        self.project_id = settings.GCP_PROJECT_ID
        self.location = settings.GCP_LOCATION
        self.storage_client = None
        self.speech_client = None
        self.genai_client = None
        self._init_clients()

    def _init_clients(self) -> None:
        """Attempt initializing GCP clients using Application Default Credentials (ADC)."""
        try:
            from google.cloud import storage
            self.storage_client = storage.Client(project=self.project_id)
            logger.info("Initialized Google Cloud Storage client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google Cloud Storage client not initialized with ADC (fallback to local): {e}")

        try:
            from google.cloud import speech_v2
            self.speech_client = speech_v2.SpeechClient()
            logger.info("Initialized Google Cloud Speech-to-Text v2 client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google Cloud Speech-to-Text client not initialized with ADC: {e}")

        try:
            from google import genai
            self.genai_client = genai.Client()
            logger.info("Initialized Google GenAI / Vertex AI client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google GenAI client not initialized with ADC / API key: {e}")


gcp_manager = GCPClientManager()
