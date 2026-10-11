"""Idempotent delivery of durable jobs into real persisted ADK function calls."""

import hashlib
import time
import uuid

from google.adk.events import Event
from google.genai import types


class JobResultBridge:
    def __init__(self, service):
        self.service, self.repo = service, service.repo

    def _path(self, session_id, call_id):
        session_path = self.service._path("vibeshorts", self.service.uid, session_id)
        return session_path + "/pending_calls/" + hashlib.sha256(call_id.encode()).hexdigest()

    async def associate(self, session_id, call_id, job_id):
        session = await self.service.get_session(
            app_name="vibeshorts", user_id=self.service.uid, session_id=session_id
        )
        match = next(
            (
                (event, call)
                for event in session.events
                for call in event.get_function_calls()
                if call.id == call_id
            ),
            None,
        )
        if not match:
            raise ValueError("Only real persisted ADK calls can await jobs")
        event, call = match
        path = self._path(session_id, call_id)
        value = {
            "session_id": session_id,
            "call_id": call_id,
            "name": call.name,
            "invocation_id": event.invocation_id,
            "job_id": job_id,
            "project_id": self.service.project_id,
            "uid": self.service.uid,
            "status": "waiting",
            "lease_until": 0,
            "version": 1,
        }

        def save(tx):
            self.service._authorize(tx)
            job = tx.get(f"projects/{self.service.project_id}/jobs/{job_id}")
            if not job or job["caller"]["uid"] != self.service.uid:
                raise PermissionError("Job ownership mismatch")
            previous = tx.get(path)
            if previous and previous["job_id"] != job_id:
                raise ValueError("Function call already associated with another job")
            if not previous:
                tx.set(path, value)

        self.repo.atomic(save)

    async def deliver(self, session_id, call_id):
        path, owner = self._path(session_id, call_id), uuid.uuid4().hex

        def claim(tx):
            self.service._authorize(tx)
            session_path = self.service._path("vibeshorts", self.service.uid, session_id)
            record = tx.get(session_path)
            if record.get("delivery_lease_until", 0) > time.time():
                return None
            pending = tx.get(path)
            if not pending or pending["status"] == "delivered" or pending["lease_until"] > time.time():
                return None
            job = tx.get(f"projects/{self.service.project_id}/jobs/{pending['job_id']}")
            if job["status"] not in {"succeeded", "failed", "cancelled", "submission_unknown"}:
                return None
            pending.update(lease_owner=owner, lease_until=time.time() + 30, version=pending["version"] + 1)
            record.update(delivery_owner=owner, delivery_lease_until=time.time() + 30)
            tx.set(session_path, record)
            tx.set(path, pending)
            return pending, {
                k: job.get(k) for k in ("job_id", "run_id", "status", "artifact_ids", "error", "costs")
            }

        claimed = self.repo.atomic(claim)
        if not claimed:
            return False
        pending, result = claimed
        session = await self.service.get_session(
            app_name="vibeshorts", user_id=self.service.uid, session_id=session_id
        )
        event = Event(
            id="job_result_" + hashlib.sha256(call_id.encode()).hexdigest(),
            author="user",
            invocation_id=pending["invocation_id"],
            content=types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call_id, name=pending["name"], response=result
                        )
                    )
                ],
            ),
        )
        # Event identity makes a crash after append/before marker safe to redeliver.
        await self.service.append_event(session, event)

        def finish(tx):
            current = tx.get(path)
            if current.get("lease_owner") != owner or current["lease_until"] <= time.time():
                raise ValueError("Result-delivery lease expired")
            current.update(status="delivered", lease_until=0, delivered_event_id=event.id)
            tx.set(path, current)
            session_path = self.service._path("vibeshorts", self.service.uid, session_id)
            record = tx.get(session_path)
            if record.get("delivery_owner") == owner:
                record["delivery_lease_until"] = 0
                tx.set(session_path, record)

        self.repo.atomic(finish)
        return True
