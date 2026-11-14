"""The process's connection pool, opened with the application and closed with it."""

from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.core.settings import Settings

CONNECT_TIMEOUT_S = 5  # libpq's own wait for one connection; the pool retries on its own
# psycopg_pool's default of 300 s, with a backoff that doubles, left a pod unready for minutes
# after the database was back; a chain given up early starts anew at the next request
RECONNECT_TIMEOUT_S = 10
CONNECTION_OPTIONS: dict[str, Any] = {
    "connect_timeout": CONNECT_TIMEOUT_S,
    "application_name": "curricarta",
    # A peer gone without a word (stalled network) is noticed within some 30 s, not hours;
    # tcp_user_timeout takes effect where the system has it (Linux)
    "keepalives": 1,
    "keepalives_idle": 10,
    "keepalives_interval": 5,
    "keepalives_count": 3,
    "tcp_user_timeout": 10_000,
}
# The server's side of it: a client gone without a word (its host down, the network cut) is noticed in
# some 60 s, and the locks of its open transaction go - its job's row among them, which a sweep passes by
SERVER_KEEPALIVES = {"tcp_keepalives_idle": 30, "tcp_keepalives_interval": 10, "tcp_keepalives_count": 3}


def session_options(settings: Settings) -> str:
    """libpq's ``options`` for the pool's sessions: the timeouts the settings set (a 0 is none, and left
    out), then the server's keepalives. The commands' connections (CONNECTION_OPTIONS) take none: the
    migration waits for another's lock as long as it runs.

    Behind PgBouncer, which may refuse ``options`` at the start of a session, the same values are set by
    ``ALTER ROLE … SET`` (docs/uebergabe/konfiguration.md)."""
    values = {
        "idle_in_transaction_session_timeout": settings.db_idle_in_transaction_timeout_s * 1000,
        "statement_timeout": settings.db_statement_timeout_s * 1000,
    }
    chosen = {name: value for name, value in values.items() if value} | SERVER_KEEPALIVES
    return " ".join(f"-c {name}={value}" for name, value in chosen.items())


def create_pool(settings: Settings, *, name: str = "curricarta") -> AsyncConnectionPool:
    """A pool that is not open yet; ``await pool.open(wait=False)`` starts it without the database.

    A connection is checked before it is handed out: after a database restart the pool's
    connections are cut, and each would otherwise fail one request. ``name`` is the sessions'
    application_name: pg_stat_activity tells the API's from the worker's by it.
    """
    return AsyncConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        kwargs={**CONNECTION_OPTIONS, "application_name": name, "options": session_options(settings)},
        check=AsyncConnectionPool.check_connection,
        timeout=settings.db_pool_timeout_s,
        reconnect_timeout=RECONNECT_TIMEOUT_S,
        open=False,
        name="curricarta",
    )
