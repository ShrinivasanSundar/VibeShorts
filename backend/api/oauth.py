import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from tools.commands import checked_id, identifier
from tools.contracts.errors import AppError
from tools.contracts.models import READ, SCOPES, Caller


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class OAuthBroker:
    def __init__(self, commands):
        self.commands, self.repo, self.settings = commands, commands.repo, commands.settings
        self.resource = self.settings.public_url.rstrip("/") + "/mcp"

    def metadata(self):
        base = self.settings.public_url.rstrip("/")
        return {
            "issuer": base,
            "authorization_endpoint": base + "/oauth/authorize",
            "token_endpoint": base + "/oauth/token",
            "revocation_endpoint": base + "/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": sorted(SCOPES),
        }

    def begin(
        self,
        client_id,
        redirect_uri,
        resource,
        scope,
        state,
        code_challenge,
        code_challenge_method,
        response_type,
    ):
        client = self.settings.clients.get(client_id)
        if not client or redirect_uri not in client["redirect_uris"]:
            raise AppError("invalid_request", "Unregistered client or redirect URI", 400)
        redirect = urlparse(redirect_uri)
        if redirect.fragment or (
            redirect.scheme != "https"
            and not (redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1", "::1"})
        ):
            raise AppError("invalid_request", "Redirect must use HTTPS or loopback HTTP", 400)
        if (
            response_type != "code"
            or resource != self.resource
            or code_challenge_method != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge)
        ):
            raise AppError("invalid_request", "Code flow, exact MCP resource and S256 PKCE are required", 400)
        scopes = sorted(set(scope.split()))
        if READ not in scopes or not set(scopes) <= SCOPES:
            raise AppError("invalid_scope", "Unsupported or missing read scope", 400)
        if len(state) > 1000:
            raise AppError("invalid_request", "State exceeds permitted length", 400)
        request_id = secrets.token_urlsafe(32)
        self.repo.atomic(
            lambda tx: tx.set(
                "oauth_requests/" + token_hash(request_id),
                {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "resource": resource,
                    "scopes": scopes,
                    "state": state,
                    "challenge": code_challenge,
                    "expires_at": self.commands.clock() + 300,
                    "used": False,
                },
            )
        )
        return self.settings.web_url.rstrip("/") + "/consent?" + urlencode({"request_id": request_id})

    def request_details(self, caller, request_id):
        self.commands.provision(caller)
        request = self.repo.get("oauth_requests/" + token_hash(request_id))
        if not request or request["used"] or request["expires_at"] <= self.commands.clock():
            raise AppError("invalid_request", "Authorization request expired", 400)
        return {
            "client_name": self.settings.clients[request["client_id"]]["name"],
            "scopes": request["scopes"],
            "projects": self.commands.list_projects(caller).data["projects"],
        }

    def consent(self, caller, request_id, projects, approved):
        self.commands.provision(caller)
        if len(projects) > 100 or len(projects) != len(set(projects)):
            raise AppError("invalid_request", "Invalid project selection", 400)

        def apply(tx):
            request_path = "oauth_requests/" + token_hash(request_id)
            request = tx.get(request_path)
            if not request or request["used"] or request["expires_at"] <= self.commands.clock():
                raise AppError("invalid_request", "Authorization request expired", 400)
            request["used"] = True
            tx.set(request_path, request)
            if not approved:
                return request["redirect_uri"], {"error": "access_denied", "state": request["state"]}
            if not projects:
                raise AppError("invalid_request", "Select at least one project", 400)
            for project_id in projects:
                for scope in request["scopes"]:
                    self.commands.authorize(caller, project_id, scope, tx)
            grant_id = identifier("grant")
            user = tx.get("users/" + checked_id(caller.uid))
            tx.set(
                "oauth_grants/" + grant_id,
                {
                    "id": grant_id,
                    "uid": caller.uid,
                    "auth_time": caller.auth_time,
                    "projects": projects,
                    "scopes": request["scopes"],
                    "client_id": request["client_id"],
                    "resource": self.resource,
                    "access_version": user["access_version"],
                    "revoked": False,
                },
            )
            code = secrets.token_urlsafe(32)
            tx.set(
                "oauth_codes/" + token_hash(code),
                {
                    "grant_id": grant_id,
                    "redirect_uri": request["redirect_uri"],
                    "challenge": request["challenge"],
                    "expires_at": self.commands.clock() + 120,
                    "used": False,
                },
            )
            return request["redirect_uri"], {"code": code, "state": request["state"]}

        redirect, parameters = self.repo.atomic(apply)
        parts = urlparse(redirect)
        return urlunparse(parts._replace(query=urlencode(parse_qsl(parts.query) + list(parameters.items()))))

    def _grant(self, tx, grant_id, client_id, resource):
        grant = tx.get("oauth_grants/" + checked_id(grant_id))
        if not grant or grant["revoked"] or grant["client_id"] != client_id or grant["resource"] != resource:
            raise AppError("invalid_grant", "Grant is invalid", 400)
        self.commands.identity.check_uid(grant["uid"], grant["auth_time"])
        user = tx.get("users/" + checked_id(grant["uid"]))
        if not user or not user["access_enabled"] or user["access_version"] != grant["access_version"]:
            raise AppError("invalid_grant", "Grant access revoked", 400)
        caller = Caller(
            uid=grant["uid"],
            auth_time=grant["auth_time"],
            projects=grant["projects"],
            scopes=grant["scopes"],
            grant_id=grant["id"],
        )
        for project_id in grant["projects"]:
            for scope in grant["scopes"]:
                self.commands.authorize(caller, project_id, scope, tx)
        return grant

    def _mint(self, tx, grant):
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        now = self.commands.clock()
        for raw, kind, expiry in ((access, "access", now + 900), (refresh, "refresh", now + 7 * 86400)):
            tx.set(
                "oauth_tokens/" + token_hash(raw),
                {
                    "grant_id": grant["id"],
                    "kind": kind,
                    "expires_at": expiry,
                    "used": False,
                },
            )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": 900,
            "refresh_token": refresh,
            "scope": " ".join(grant["scopes"]),
        }

    def exchange(self, parameters):
        client_id, resource = parameters.get("client_id"), parameters.get("resource")
        if client_id not in self.settings.clients or resource != self.resource:
            raise AppError("invalid_request", "Registered client and exact resource are required", 400)

        def apply(tx):
            if parameters.get("grant_type") == "authorization_code":
                path = "oauth_codes/" + token_hash(parameters.get("code", ""))
                code = tx.get(path)
                verifier = parameters.get("code_verifier", "")
                if (
                    not code
                    or code["used"]
                    or code["expires_at"] <= self.commands.clock()
                    or code["redirect_uri"] != parameters.get("redirect_uri")
                    or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                    or pkce_challenge(verifier) != code["challenge"]
                ):
                    raise AppError("invalid_grant", "Authorization code or PKCE proof is invalid", 400)
                grant = self._grant(tx, code["grant_id"], client_id, resource)
                code["used"] = True
                tx.set(path, code)
                return self._mint(tx, grant)
            if parameters.get("grant_type") == "refresh_token":
                path = "oauth_tokens/" + token_hash(parameters.get("refresh_token", ""))
                token = tx.get(path)
                if not token or token["kind"] != "refresh" or token["expires_at"] <= self.commands.clock():
                    raise AppError("invalid_grant", "Refresh token is invalid", 400)
                grant = self._grant(tx, token["grant_id"], client_id, resource)
                if token["used"]:
                    grant["revoked"] = True
                    tx.set("oauth_grants/" + grant["id"], grant)
                    # Return the error after committing the family revocation.
                    return {"error": "invalid_grant"}
                token["used"] = True
                tx.set(path, token)
                return self._mint(tx, grant)
            raise AppError("unsupported_grant_type", "Unsupported grant type", 400)

        result = self.repo.atomic(apply)
        if "error" in result:
            raise AppError("invalid_grant", "Refresh reuse revoked this grant", 400)
        return result

    def verify(self, raw_token):
        def apply(tx):
            token = tx.get("oauth_tokens/" + token_hash(raw_token))
            if not token or token["kind"] != "access" or token["expires_at"] <= self.commands.clock():
                raise AppError("UNAUTHENTICATED", "MCP token invalid or expired", 401)
            grant = tx.get("oauth_grants/" + token["grant_id"])
            grant = self._grant(tx, token["grant_id"], (grant or {}).get("client_id"), self.resource)
            return (
                Caller(
                    uid=grant["uid"],
                    auth_time=grant["auth_time"],
                    projects=grant["projects"],
                    scopes=grant["scopes"],
                    grant_id=grant["id"],
                ),
                token["expires_at"],
                grant["client_id"],
            )

        return self.repo.atomic(apply)

    def revoke(self, raw_token, client_id):
        def apply(tx):
            token = tx.get("oauth_tokens/" + token_hash(raw_token))
            if token:
                grant = tx.get("oauth_grants/" + token["grant_id"])
                if grant and grant["client_id"] == client_id:
                    grant["revoked"] = True
                    tx.set("oauth_grants/" + grant["id"], grant)

        self.repo.atomic(apply)
