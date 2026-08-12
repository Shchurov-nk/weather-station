from psycopg_pool import ConnectionPool

from config import settings

# The pool is not about throughput (one sensor, one request a minute) —
# it re-establishes connections when Postgres restarts, instead of the
# old open-connection-per-request that just died with it.
_pool = None


def get_pool():
    # Lazy so importing the app (e.g. in tests) doesn't dial the database.
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url, min_size=1, max_size=4, open=True
        )
    return _pool
