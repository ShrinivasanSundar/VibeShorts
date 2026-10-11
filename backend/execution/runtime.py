import os

from api.oauth import OAuthBroker
from execution.config import Settings
from execution.identity import FirebaseIdentity
from execution.repository import FirestoreRepository
from execution.storage import CloudStorage
from providers.image import FixtureImageProvider, VertexImageProvider
from tools.commands import Commands
from worker.image import ImageWorker


class Runtime:
    def __init__(self, commands):
        self.commands = commands
        self.oauth = OAuthBroker(commands)
        self.worker = ImageWorker(commands)

    @classmethod
    def create(cls):
        settings = Settings()
        if settings.mode == "emulator":
            required = (
                "FIREBASE_AUTH_EMULATOR_HOST",
                "FIRESTORE_EMULATOR_HOST",
                "STORAGE_EMULATOR_HOST",
                "PUBSUB_EMULATOR_HOST",
            )
            if any(not os.getenv(key) for key in required):
                raise ValueError("Emulator mode requires Auth, Firestore, Storage and Pub/Sub emulator hosts")
            if settings.provider == "fixture" and not settings.google_cloud_project.startswith("demo-"):
                raise ValueError(
                    "Fixture emulator execution requires a demo- project to avoid live service access"
                )
        provider = FixtureImageProvider() if settings.provider == "fixture" else VertexImageProvider(settings)
        return cls(
            Commands(
                FirestoreRepository(settings.google_cloud_project),
                CloudStorage(settings),
                FirebaseIdentity(settings),
                provider,
                settings,
            )
        )
