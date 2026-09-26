"""Configuration and environment settings for VibeShorts."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings validated at runtime."""

    # Project Information
    APP_NAME: str = "VibeShorts Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Google Cloud Platform
    GCP_PROJECT_ID: str = "vibeshorts-dev"
    GCP_LOCATION: str = "us-central1"
    GCS_BUCKET_NAME: str = "vibeshorts-media-bucket"
    GCP_STT_RECOGNIZER: str = "_"  # Default global recognizer or custom recognizer id

    # Gemini & Vertex AI Models
    GEMINI_DIRECTOR_MODEL: str = "gemini-1.5-pro"
    GEMINI_LABELER_MODEL: str = "gemini-1.5-flash"
    GEMINI_REVIEWER_MODEL: str = "gemini-1.5-pro"
    GEMINI_MICRO_PROBE_MODEL: str = "gemini-1.5-flash"

    # Workflow Governance
    MAX_REVIEW_RETRIES: int = 2
    TARGET_ASPECT_RATIO: str = "9:16"
    TARGET_WIDTH: int = 1080
    TARGET_HEIGHT: int = 1920

    # Local Storage Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    TEMP_DIR: Path = STORAGE_DIR / "temp"
    OUTPUT_DIR: Path = STORAGE_DIR / "outputs"

    # External Binaries & Services
    FFMPEG_PATH: str = "ffmpeg"
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def init_directories(self) -> None:
        """Ensure necessary local storage paths exist."""
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.init_directories()
