"""Recognize completed director failures from persisted, correlated ADK events.

Transport interruptions without a terminal event remain uncertain. Reading this
evidence never invokes a model or assumes that missing output means no charge.
"""

import hashlib


def director_failure(repo, job):
    if job.get("kind") not in {"director_turn", "storyboard", "edit"}:
        return None
    correlation = job.get("director") or {}
    if not all(correlation.get(key) for key in ("session_id", "invocation_id", "last_event_id")):
        return None
    uid = job["caller"]["uid"]
    identity = f"vibeshorts:{job['project_id']}:{uid}:{correlation['session_id']}"
    path = "adk_sessions/" + hashlib.sha256(identity.encode()).hexdigest()
    session = repo.get(path)
    if not session or session.get("project_id") != job["project_id"] or session.get("user_id") != uid:
        return None
    row = repo.get(path + "/events/" + correlation["last_event_id"])
    event = row.get("event", {}) if row else {}
    if (
        event.get("invocation_id") != correlation["invocation_id"]
        or event.get("error_code") != "LlmCallsLimitExceededError"
    ):
        return None
    usage = {"llm_calls": 0, "prompt_token_count": 0, "candidates_token_count": 0, "total_token_count": 0}
    for row in repo.list(path + "/events"):
        event = row["event"]
        if event.get("invocation_id") != correlation["invocation_id"]:
            continue
        metadata = event.get("usage_metadata")
        if metadata:
            usage["llm_calls"] += 1
            for key in ("prompt_token_count", "candidates_token_count", "total_token_count"):
                usage[key] += metadata.get(key, 0) or 0
    return usage


def recover_director_failure(commands, job):
    """Settle a proven terminal failure once; never submit replacement work."""
    from execution.telemetry import event
    from tools.commands import project_path
    from tools.contracts.errors import AppError

    usage = director_failure(commands.repo, job)
    if usage is None:
        return False
    if job.get("candidate_path") and commands.storage.get(job["candidate_path"]):
        return False

    def apply(tx):
        current = tx.get(project_path(job["project_id"], "jobs", job["job_id"]))
        if (
            not current
            or current["status"] in {"succeeded", "failed", "cancelled"}
            or current["lease_expires_at"] > commands.clock()
            or current.get("director") != job.get("director")
            or current["attempt"] != job["attempt"]
            or current.get("candidate_path") != job.get("candidate_path")
        ):
            return False
        current["lease_owner"], current["lease_expires_at"] = None, 0
        commands.settle(
            tx, current, current["provider"]["reservation_micros"], "conservative_estimate", usage
        )
        current["error"] = AppError(
            "DIRECTOR_CALL_LIMIT",
            "The director couldn’t finish its reply. Please retry your message.",
            retryable=True,
            action="retry",
            job_id=current["job_id"],
        ).payload.model_dump()
        commands.transition(tx, current, "cancelled" if current["cancel_requested"] else "failed")
        event("director_failure_recovered", job_id=current["job_id"])
        return True

    return commands.repo.atomic(apply)
