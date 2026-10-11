import io

import pytest
from PIL import Image

from execution.config import Settings
from execution.identity import TestIdentity
from execution.repository import MemoryRepository
from execution.runtime import Runtime
from execution.storage import MemoryStorage
from providers.image import FixtureImageProvider
from tools.commands import Commands
from tools.contracts.models import Caller, ImageCommand, ImageInput, ProjectCreate


class Clock:
    def __init__(self):
        self.now = 2_000_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=181):
        self.now += seconds


@pytest.fixture
def runtime():
    clock = Clock()
    commands = Commands(
        MemoryRepository(), MemoryStorage(), TestIdentity(), FixtureImageProvider(), Settings(), clock
    )
    return Runtime(commands)


@pytest.fixture
def alice(runtime):
    caller = Caller(uid="alice", auth_time=runtime.commands.clock())
    runtime.commands.provision(caller)
    return caller


@pytest.fixture
def bob(runtime):
    caller = Caller(uid="bob", auth_time=runtime.commands.clock())
    runtime.commands.provision(caller)
    return caller


@pytest.fixture
def project(runtime, alice):
    return runtime.commands.create_project(
        alice, ProjectCreate(name="Launch", idempotency_key="project-1")
    ).data["project_id"]


@pytest.fixture
def submit(runtime, alice, project):
    def create(key="image-1", **input):
        return runtime.commands.generate_image(
            alice,
            ImageCommand(
                project_id=project, idempotency_key=key, input=ImageInput(prompt="Product reveal", **input)
            ),
        )

    return create


@pytest.fixture
def png():
    image = Image.new("RGB", (90, 160), "blue")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
