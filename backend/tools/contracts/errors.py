from tools.contracts.models import PublicError


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, **kwargs):
        self.status = status
        self.payload = PublicError(code=code, message=message, **kwargs)
        super().__init__(message)
