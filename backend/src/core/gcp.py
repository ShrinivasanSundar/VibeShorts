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
        self.firestore_client = None
        self._init_clients()

    def _init_clients(self) -> None:
        """Attempt initializing GCP clients using Application Default Credentials (ADC)."""
        import os
        if settings.GOOGLE_APPLICATION_CREDENTIALS and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS

        # Attempt loading explicit Service Account credentials if configured
        creds = None
        cred_path = settings.GOOGLE_APPLICATION_CREDENTIALS
        if cred_path:
            from pathlib import Path
            path_obj = Path(cred_path)
            if not path_obj.is_absolute():
                # Check relative to backend directory or base dir
                candidate = settings.BASE_DIR / cred_path
                if candidate.exists():
                    path_obj = candidate
            if path_obj.exists():
                try:
                    from google.oauth2 import service_account
                    creds = service_account.Credentials.from_service_account_file(str(path_obj))
                    logger.info(f"Loaded GCP credentials from file: {path_obj}")
                except Exception as e:
                    logger.warning(f"Failed to load credentials file {path_obj}: {e}")

        try:
            from google.cloud import storage
            self.storage_client = storage.Client(project=self.project_id, credentials=creds)
            logger.info("Initialized Google Cloud Storage client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google Cloud Storage client not initialized (fallback to local): {e}")

        try:
            from google.cloud import speech_v2
            self.speech_client = speech_v2.SpeechClient(credentials=creds)
            logger.info("Initialized Google Cloud Speech-to-Text v2 client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google Cloud Speech-to-Text client not initialized: {e}")

        try:
            from google import genai
            if settings.GEMINI_API_KEY:
                self.genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            else:
                self.genai_client = genai.Client()
            logger.info("Initialized Google GenAI / Vertex AI client")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google GenAI client not initialized with ADC / API key: {e}")

        try:
            from google.cloud import firestore
            self.firestore_client = firestore.AsyncClient(project=self.project_id, credentials=creds)
            logger.info(f"Initialized Google Cloud Firestore client for project '{self.project_id}'")
        except (DefaultCredentialsError, Exception) as e:
            logger.warning(f"Google Cloud Firestore client not initialized: {e}")


gcp_manager = GCPClientManager()

