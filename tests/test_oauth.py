from urllib.parse import parse_qs, urlparse

import pytest

from apps.api.oauth import pkce_challenge, token_hash
from tools.contracts.errors import AppError

VERIFIER = "v" * 64
REDIRECT = "http://127.0.0.1:8765/callback"


def authorization(runtime, alice, project, scopes="vibeshorts:read vibeshorts:generate vibeshorts:cancel"):
    broker = runtime.oauth
    consent = broker.begin(
        "vibeshorts-sdk",
        REDIRECT,
        broker.resource,
        scopes,
        "expected-state",
        pkce_challenge(VERIFIER),
        "S256",
        "code",
    )
    request_id = parse_qs(urlparse(consent).query)["request_id"][0]
    callback = broker.consent(alice, request_id, [project], True)
    assert parse_qs(urlparse(callback).query)["state"] == ["expected-state"]
    code = parse_qs(urlparse(callback).query)["code"][0]
    return {
        "grant_type": "authorization_code",
        "client_id": "vibeshorts-sdk",
        "resource": broker.resource,
        "redirect_uri": REDIRECT,
        "code": code,
        "code_verifier": VERIFIER,
    }


def test_pkce_code_single_use_and_only_hashes_persisted(runtime, alice, project):
    parameters = authorization(runtime, alice, project)
    with pytest.raises(AppError):
        runtime.oauth.exchange({**parameters, "code_verifier": "wrong" * 16})
    tokens = runtime.oauth.exchange(parameters)
    caller, expiry, _ = runtime.oauth.verify(tokens["access_token"])
    assert caller.uid == "alice" and caller.projects == [project]
    assert expiry == runtime.commands.clock() + 900
    assert runtime.commands.repo.get("oauth_tokens/" + token_hash(tokens["access_token"]))
    assert not runtime.commands.repo.get("oauth_tokens/" + tokens["access_token"])
    with pytest.raises(AppError):
        runtime.oauth.exchange(parameters)
    with pytest.raises(AppError):
        runtime.oauth.verify("alice")


@pytest.mark.parametrize(
    "changes",
    [
        {"resource": "https://other/mcp"},
        {"redirect_uri": "https://evil/cb"},
        {"client_id": "not-registered"},
        {"code_challenge_method": "plain"},
        {"scope": "admin"},
    ],
)
def test_invalid_authorization_requests(runtime, changes):
    args = dict(
        client_id="vibeshorts-sdk",
        redirect_uri=REDIRECT,
        resource=runtime.oauth.resource,
        scope="vibeshorts:read",
        state="state",
        code_challenge=pkce_challenge(VERIFIER),
        code_challenge_method="S256",
        response_type="code",
    )
    with pytest.raises(AppError):
        runtime.oauth.begin(**{**args, **changes})


def test_refresh_rotation_and_reuse_revokes_entire_grant(runtime, alice, project):
    first = runtime.oauth.exchange(authorization(runtime, alice, project))
    parameters = {
        "grant_type": "refresh_token",
        "client_id": "vibeshorts-sdk",
        "resource": runtime.oauth.resource,
        "refresh_token": first["refresh_token"],
    }
    second = runtime.oauth.exchange(parameters)
    assert second["refresh_token"] != first["refresh_token"]
    with pytest.raises(AppError):
        runtime.oauth.exchange(parameters)
    for raw in (first["access_token"], second["access_token"]):
        with pytest.raises(AppError):
            runtime.oauth.verify(raw)


def test_token_expiry_audience_scope_and_user_revocation(runtime, alice, project, submit):
    first = runtime.oauth.exchange(authorization(runtime, alice, project, "vibeshorts:read"))
    caller, _, _ = runtime.oauth.verify(first["access_token"])
    with pytest.raises(AppError):
        runtime.commands.cancel_job(caller, project, submit().job_id, "cancel")
    with pytest.raises(AppError):
        runtime.oauth.exchange(
            {
                "grant_type": "refresh_token",
                "client_id": "vibeshorts-sdk",
                "resource": "wrong-resource",
                "refresh_token": first["refresh_token"],
            }
        )
    runtime.commands.clock.advance(901)
    with pytest.raises(AppError):
        runtime.oauth.verify(first["access_token"])


def test_removed_membership_invalidates_existing_mcp_grant(runtime, alice, project):
    token = runtime.oauth.exchange(authorization(runtime, alice, project))["access_token"]
    path = "projects/" + project
    runtime.commands.repo.atomic(lambda tx: tx.set(path, {**tx.get(path), "members": {}}))
    with pytest.raises(AppError):
        runtime.oauth.verify(token)


def test_consent_denial_has_no_grant_and_request_cannot_be_reused(runtime, alice, project):
    broker = runtime.oauth
    consent = broker.begin(
        "vibeshorts-sdk",
        REDIRECT,
        broker.resource,
        "vibeshorts:read",
        "s",
        pkce_challenge(VERIFIER),
        "S256",
        "code",
    )
    request_id = parse_qs(urlparse(consent).query)["request_id"][0]
    callback = broker.consent(alice, request_id, [], False)
    assert parse_qs(urlparse(callback).query)["error"] == ["access_denied"]
    assert runtime.commands.repo.list("oauth_grants") == []
    with pytest.raises(AppError):
        broker.consent(alice, request_id, [project], True)
