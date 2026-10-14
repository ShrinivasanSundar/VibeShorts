"""Disposable browser fixture server: real Auth emulator, in-memory media/job state.

Run only through the Playwright configuration. No paid or cloud services are used.
"""

import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager

import uvicorn

from api.main import create_app
from execution.config import Settings
from execution.identity import FirebaseIdentity
from execution.repository import MemoryRepository
from execution.runtime import Runtime
from execution.storage import MemoryStorage
from execution.workflow import WorkflowScheduler
from providers.image import FixtureImageProvider, ImageOutput
from providers.studio import StudioProvider
from tools.commands import Commands, project_path
from tools.contracts.models import Caller

if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") != "127.0.0.1:19099":
    raise RuntimeError("Browser fixtures require the isolated Auth emulator on port 19099")

settings = Settings(
    mode="emulator",
    provider="fixture",
    google_cloud_project="demo-vibeshorts-browser",
    web_url="http://127.0.0.1:3100",
    public_url="http://127.0.0.1:8100",
)
commands = Commands(
    MemoryRepository(), MemoryStorage(), FirebaseIdentity(settings), FixtureImageProvider(), settings
)
runtime = Runtime(commands)
original_generate = StudioProvider.generate


def fixture_generate(self, request, references, snapshot, job):
    if self.kind == "render":
        caller = Caller(**job["caller"])
        manifest = self.commands.get_hyperframe(
            caller, job["project_id"], request.composition_artifact_id
        ).data["manifest"]
        aid = next(c["artifact_id"] for c in manifest["timeline"]["clips"] if c["kind"] == "video")
        data, mime = self.commands.asset_content(caller, job["project_id"], aid)
        return ImageOutput(data, mime)
    return original_generate(self, request, references, snapshot, job)


StudioProvider.generate = fixture_generate
app = create_app(runtime)
transport_lifespan = app.router.lifespan_context


async def work():
    while True:
        await asyncio.to_thread(WorkflowScheduler(commands).sweep)
        for project in commands.repo.list("projects"):
            for job in commands.repo.list(project_path(project["project_id"], "jobs")):
                if job["status"] == "queued":
                    await asyncio.to_thread(runtime.worker.execute, project["project_id"], job["job_id"])
        await asyncio.sleep(0.25)


@asynccontextmanager
async def lifespan(app):
    async with transport_lifespan(app):
        task = asyncio.create_task(work())

        def report_failure(done):
            if not done.cancelled() and done.exception():
                traceback.print_exception(done.exception())

        task.add_done_callback(report_failure)
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app.router.lifespan_context = lifespan
if __name__ == "__main__":
    logging.disable(logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
