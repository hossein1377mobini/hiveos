"""Declarative base, naming conventions and shared mixins.

Naming conventions make constraint names deterministic so downgrade()
(drop_table) and future alter() operations never depend on auto-generated
names (rollback-migration requirement from S0).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# All application tables live in this schema (created by migration 0001).
SCHEMA = "hiveos"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION, schema=SCHEMA)


class TimestampMixin:
    """created_at/updated_at maintained by the database clock."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def new_uuid() -> uuid.UUID:
    """Client-side UUID generator (PK columns also carry a DB server_default)."""
    return uuid.uuid4()
