"""Small shared helpers for varchar-stored enum values (ADR-014)."""

from enum import StrEnum


def status_value(status) -> str:
    """Normalize a possibly-enum-or-str status column value to a plain string."""
    return status.value if isinstance(status, StrEnum) else str(status)
