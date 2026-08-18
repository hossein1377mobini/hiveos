"""Structured API errors matching the OpenAPI `Error` / `ValidationProblem` shapes.

Convention:
- Domain/service failures raise an `ApiError` with a stable `error` code.
- `ValidationProblem` (422, title "Validation failed") is raised for rule
  violations carrying per-field messages, and for FastAPI body-validation
  failures we normalize the 422 detail into the same shape.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import ValidationProblem


class ApiError(Exception):
    """Base domain error mapped to an HTTP response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "bad_request"
    # Honest flag (m4): True ONLY where an AuditLog row is actually written for
    # the failure (nothing does today), so the API never claims log coverage it
    # doesn't have.
    audit_logged: bool = False

    def __init__(self, message: str | None = None, error_code: str | None = None):
        self.message = message
        if error_code:
            self.error_code = error_code
        super().__init__(message or self.error_code)


class ConflictError(ApiError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class NotFoundError(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class UnauthorizedError(ApiError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class GoneError(ApiError):
    status_code = status.HTTP_410_GONE
    error_code = "gone"


class RateLimitedError(ApiError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limited"


class GatewayUnavailableError(ApiError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "gateway_unavailable"


class ValidationError422(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "validation_failed"


def _error_payload(err: ApiError) -> dict:
    return {"error": err.error_code, "message": err.message, "auditLogged": err.audit_logged}


def _validation_problem(errors: dict[str, list[str]]) -> dict:
    return ValidationProblem(errors=errors).model_dump()


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _domain_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_error_payload(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors: dict[str, list[str]] = {}
        for item in exc.errors():
            loc = ".".join(str(p) for p in item.get("loc", []) if p not in ("body",))
            loc = loc or "body"
            msg = str(item.get("msg", "validation error")).replace("Value error, ", "")
            errors.setdefault(loc, []).append(msg)
        return JSONResponse(status_code=422, content=_validation_problem(errors))
