import time

from execution.read_context import cached_read
from tools.contracts.errors import AppError
from tools.contracts.models import Caller


class FirebaseIdentity:
    def __init__(self, settings):
        import firebase_admin

        try:
            self.app = firebase_admin.get_app(settings.google_cloud_project)
        except ValueError:
            self.app = firebase_admin.initialize_app(
                options={"projectId": settings.google_cloud_project},
                name=settings.google_cloud_project,
            )

    def verify(self, token: str) -> Caller:
        from firebase_admin import auth

        try:
            claims = auth.verify_id_token(token, app=self.app, check_revoked=True)
            if claims.get("firebase", {}).get("sign_in_provider") == "anonymous":
                raise ValueError("Anonymous sign-in is disabled")
            caller = Caller(uid=claims["uid"], auth_time=claims["auth_time"])
            # check_revoked already checked the Auth user; share that result only
            # inside an enclosing read scope, never across requests or workers.
            cached_read((id(self), caller.uid, caller.auth_time), lambda: None)
            return caller
        except Exception as exc:
            raise AppError("UNAUTHENTICATED", "Valid Firebase credentials are required", 401) from exc

    def check_uid(self, uid: str, auth_time: float):
        return cached_read((id(self), uid, auth_time), lambda: self._check_uid(uid, auth_time))

    def _check_uid(self, uid: str, auth_time: float):
        from firebase_admin import auth

        try:
            user = auth.get_user(uid, app=self.app)
            if user.disabled or user.tokens_valid_after_timestamp / 1000 > auth_time:
                raise ValueError("User credentials revoked")
        except Exception as exc:
            raise AppError("ACCESS_DENIED", "User access is disabled or revoked", 403) from exc

    def revoke(self, uid: str):
        from firebase_admin import auth

        auth.revoke_refresh_tokens(uid, app=self.app)


class TestIdentity:
    """Explicit test dependency; cannot be configured by production environment variables."""

    __test__ = False

    def __init__(self):
        self.users = {
            "alice": {"disabled": False, "valid_after": 0},
            "bob": {"disabled": False, "valid_after": 0},
        }

    def verify(self, token: str) -> Caller:
        if token not in self.users:
            raise AppError("UNAUTHENTICATED", "Valid credentials required", 401)
        caller = Caller(uid=token, auth_time=time.time())
        self.check_uid(caller.uid, caller.auth_time)
        return caller

    def check_uid(self, uid: str, auth_time: float):
        user = self.users.get(uid)
        if not user or user["disabled"] or auth_time < user["valid_after"]:
            raise AppError("ACCESS_DENIED", "User access disabled", 403)

    def revoke(self, uid: str):
        self.users[uid]["valid_after"] = time.time()
