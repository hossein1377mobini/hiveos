"""Alembic environment - DB URL comes from app settings (env), never hardcoded (ADR-022)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Alembic runs sync engine; app uses asyncpg - derive sync URL (psycopg) for migrations.
sync_url = settings.database_url.replace('+asyncpg', '+psycopg')


def run_migrations_offline() -> None:
    context.configure(url=sync_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sync_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
