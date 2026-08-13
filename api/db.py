import psycopg

from config import DATABASE_URL


def get_conn():
    """A fresh connection per request. One sensor posting once a minute
    doesn't need a pool, and reconnecting after a db restart happens
    naturally: the next request just dials again."""
    return psycopg.connect(DATABASE_URL)
