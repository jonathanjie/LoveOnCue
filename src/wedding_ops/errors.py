class OpsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: object | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def denied(message: str = "Your role does not permit this action") -> OpsError:
    return OpsError("forbidden", message, 403)


def missing() -> OpsError:
    # The same response for nonexistent and out-of-cell IDs avoids existence leaks.
    return OpsError("not_found", "The requested record is not available", 404)


def conflict(message: str) -> OpsError:
    return OpsError("conflict", message, 409)
