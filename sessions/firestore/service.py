"""Project-owned ADK BaseSessionService; imported only by the isolated ADK environment."""

import hashlib
import time
import uuid

from google.adk.events import Event
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import ListSessionsResponse


class FirestoreSessionService(BaseSessionService):
    def __init__(self, repository, project_id, uid):
        self.repo, self.project_id, self.uid = repository, project_id, uid

    def _path(self, app_name, user_id, session_id):
        if user_id != self.uid or app_name != "vibeshorts":
            raise PermissionError("Session identity is bound to the trusted invocation")
        digest = hashlib.sha256(f"{app_name}:{self.project_id}:{user_id}:{session_id}".encode()).hexdigest()
        return "adk_sessions/" + digest

    def _authorize(self, tx=None):
        read = tx.get if tx else self.repo.get
        user = read("users/" + self.uid)
        project = read("projects/" + self.project_id)
        if (
            not user
            or not user["access_enabled"]
            or not project
            or project["members"].get(self.uid) not in {"owner", "editor"}
        ):
            raise PermissionError("Project access revoked")

    async def create_session(self, *, app_name, user_id, state=None, session_id=None, **kwargs):
        session_id = session_id or uuid.uuid4().hex
        path = self._path(app_name, user_id, session_id)

        def apply(tx):
            self._authorize(tx)
            previous = tx.get(path)
            if previous:
                return previous
            record = {
                "id": session_id,
                "app_name": app_name,
                "user_id": user_id,
                "project_id": self.project_id,
                "state": state or {},
                "version": 0,
                "last_update_time": time.time(),
                "schema_version": 1,
                "adk_version": "2.11.0",
            }
            tx.set(path, record)
            return record

        record = self.repo.atomic(apply)
        return self._session(record, [])

    def _session(self, record, events):
        state = {**record["state"], "_vibeshorts_version": record["version"]}
        for scope, path in [
            ("app", "adk_app_state/" + self.project_id),
            ("user", "adk_user_state/" + self.project_id + "_" + self.uid),
        ]:
            state.update(
                {scope + ":" + k: v for k, v in (self.repo.get(path) or {}).get("state", {}).items()}
            )
        return Session(
            id=record["id"],
            app_name=record["app_name"],
            user_id=record["user_id"],
            state=state,
            events=events,
            last_update_time=record["last_update_time"],
        )

    async def get_session(self, *, app_name, user_id, session_id, config=None, **kwargs):
        self._authorize()
        path = self._path(app_name, user_id, session_id)
        record = self.repo.get(path)
        if not record:
            return None
        events = sorted(self.repo.list(path + "/events"), key=lambda e: e["sequence"])
        if config and getattr(config, "after_timestamp", None):
            events = [e for e in events if e["event"]["timestamp"] > config.after_timestamp]
        if config and getattr(config, "num_recent_events", None):
            events = events[-config.num_recent_events :]
        return self._session(record, [Event.model_validate(e["event"]) for e in events])

    async def list_sessions(self, *, app_name, user_id, **kwargs):
        self._authorize()
        self._path(app_name, user_id, "validation")
        records = [
            r
            for r in self.repo.list("adk_sessions")
            if r["project_id"] == self.project_id and r["user_id"] == user_id and r["app_name"] == app_name
        ]
        return ListSessionsResponse(sessions=[self._session(r, []) for r in records])

    async def delete_session(self, *, app_name, user_id, session_id, **kwargs):
        self._authorize()
        path = self._path(app_name, user_id, session_id)
        for pending in self.repo.list(path + "/pending_calls"):
            key = hashlib.sha256(pending["call_id"].encode()).hexdigest()
            self.repo.atomic(lambda tx, key=key: tx.delete(path + "/pending_calls/" + key))
        for item in self.repo.list(path + "/events"):
            self.repo.atomic(lambda tx, item=item: tx.delete(path + "/events/" + item["event"]["id"]))
        self.repo.atomic(lambda tx: tx.delete(path))

    async def append_event(self, session, event):
        if event.partial:
            return event
        path = self._path(session.app_name, session.user_id, session.id)

        def apply(tx):
            self._authorize(tx)
            record = tx.get(path)
            if not record:
                raise ValueError("Session does not exist")
            if tx.get(path + "/events/" + event.id):
                return record
            if record["version"] != session.state.get("_vibeshorts_version", 0):
                raise ValueError("Concurrent session append; reload before retry")
            delta = event.actions.state_delta if event.actions else {}
            for key, value in delta.items():
                if key.startswith("temp:"):
                    continue
                if key.startswith(("app:", "user:")):
                    scope, entry = key.split(":", 1)
                    scoped_path = (
                        "adk_app_state/" + self.project_id
                        if scope == "app"
                        else "adk_user_state/" + self.project_id + "_" + self.uid
                    )
                    scoped = tx.get(scoped_path) or {"state": {}}
                    scoped["state"][entry] = value
                    tx.set(scoped_path, scoped)
                else:
                    record["state"][key] = value
            record["version"] += 1
            record["last_update_time"] = event.timestamp
            tx.set(path, record)
            tx.set(
                path + "/events/" + event.id,
                {"event": event.model_dump(mode="json", exclude_none=True), "sequence": record["version"]},
            )
            return record

        record = self.repo.atomic(apply)
        session.state.update(record["state"])
        session.state["_vibeshorts_version"] = record["version"]
        session.last_update_time = record["last_update_time"]
        if not any(e.id == event.id for e in session.events):
            session.events.append(event)
        return event

    async def export_session(self, *, app_name, user_id, session_id):
        session = await self.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
        return session.model_dump(mode="json") if session else None
