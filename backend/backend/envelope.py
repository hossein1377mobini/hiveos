"""Response envelope helpers (API Design Standards).

All success responses use {success: true, data: ..., message: null}; errors
raise ApiError and are rendered by backend.api_errors handlers.
"""

from typing import Any


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": data, "message": None}
