"""The request connection pool must be sized for how long a request holds it.

Staging 2026-09-15, 20 concurrent users: SQLAlchemy's default pool (5 + 10
overflow) ran out. A request holds its connection until its response is built,
and an interactive search or chat turn runs local ONNX inference inside that
window - 6-9 s on this CPU-only host. Once the pool was exhausted even a pure
SQL read (/wallet, no inference at all) answered in 12 s and the edge gave up
with 524, which made the whole API look broken rather than just the model path.

These tests pin the configuration; the behaviour under load is measured by
scripts/load/locustfile.py.
"""

from backend import db
from backend.config import get_settings


def test_pool_is_sized_above_sqlalchemy_default() -> None:
    """The default is 5 + 10 = 15, which is below realistic concurrency."""
    settings = get_settings()
    total = settings.db_pool_size + settings.db_max_overflow
    assert total >= 30, (
        "the request pool must cover concurrent users; a request holds its "
        "connection across local inference, which takes seconds"
    )


def test_pool_stays_inside_postgres_max_connections() -> None:
    """Staging max_connections is 60 and the audit engine also connects."""
    settings = get_settings()
    total = settings.db_pool_size + settings.db_max_overflow
    assert total <= 40, "leave headroom in PostgreSQL's max_connections"


def test_engine_actually_uses_the_configured_pool() -> None:
    """A pool configured but never passed to create_async_engine is a no-op."""
    settings = get_settings()
    assert db.engine.pool.size() == settings.db_pool_size, (
        "the engine is not using db_pool_size; the settings are documented but "
        "unwired, which is exactly how the default shipped"
    )


def test_pool_checks_connections_before_use() -> None:
    """Long-lived pooled connections go stale; pre-ping is the guard."""
    assert db.engine.pool._pre_ping is True
