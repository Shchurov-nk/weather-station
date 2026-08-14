import psycopg

from config import DATABASE_URL


def get_conn():
    """A fresh connection per query, same as the api. The 60 s
    st.cache_data ttl means a handful of connects per minute at most."""
    return psycopg.connect(DATABASE_URL)
