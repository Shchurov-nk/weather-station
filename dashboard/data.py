"""Every query the dashboard runs, shared by the chart modules. Aggregation
and the UTC -> local conversion happen in SQL: at one reading per 6 s,
14 days are ~200k rows, and the db ships back a few thousand at most."""

from datetime import datetime
from typing import NamedTuple

import pandas as pd
import streamlit as st

from config import DASHBOARD_TZ
from db import get_conn

# Heatmap / histogram bin sizes, °C and %.
T_STEP = 0.5
H_STEP = 2.0
# A reading "lasts" until the next one, but at most this long: a burst of
# readings (flaky contact) can't inflate a bin, and sensor downtime isn't
# credited to the last value seen before it.
GAP_CAP_S = 300


class Latest(NamedTuple):
    reading_time: datetime  # timestamptz, tz-aware UTC
    temperature: float
    humidity: float


def latest() -> Latest | None:
    # Uncached on purpose: the header is about liveness, and the newest
    # row on the DESC index is effectively free.
    with get_conn() as conn:
        row = conn.execute(
            "SELECT reading_time, temperature, humidity FROM sensor_readings"
            " ORDER BY reading_time DESC LIMIT 1"
        ).fetchone()
    return Latest(*row) if row else None


# Today, yesterday and the day before, as local calendar days. day_offset
# and hour are computed here, not in pandas: the container clock is UTC,
# so "today" in python would be wrong for a few hours after local midnight.
DAILY_SQL = """
    WITH m AS (
        SELECT date_trunc('minute', reading_time AT TIME ZONE %(tz)s) AS minute,
               avg(temperature) AS temperature,
               avg(humidity)    AS humidity
        FROM sensor_readings
        WHERE reading_time >= (date_trunc('day', now() AT TIME ZONE %(tz)s)
                               - interval '2 days') AT TIME ZONE %(tz)s
        GROUP BY minute
    )
    SELECT minute,
           (now() AT TIME ZONE %(tz)s)::date - minute::date AS day_offset,
           extract(epoch FROM minute::time)::float8 / 3600  AS hour,
           temperature,
           humidity
    FROM m
    ORDER BY minute
"""


@st.cache_data(ttl=60)
def load_daily() -> tuple[pd.DataFrame, datetime]:
    """1-min averages for the last 3 local days and the local "now".
    Columns: minute (naive local), day_offset (0 = today), hour (0..24),
    temperature, humidity."""
    with get_conn() as conn:
        now = conn.execute("SELECT now() AT TIME ZONE %s", (DASHBOARD_TZ,)).fetchone()[0]
        rows = conn.execute(DAILY_SQL, {"tz": DASHBOARD_TZ}).fetchall()
    cols = ["minute", "day_offset", "hour", "temperature", "humidity"]
    return pd.DataFrame(rows, columns=cols), now


def trail(daily: pd.DataFrame, now: datetime, hours: int = 12) -> pd.DataFrame:
    """Last `hours` of the daily frame as 5-min means, oldest first.
    Columns: minute, temperature, humidity."""
    recent = daily[daily["minute"] > pd.Timestamp(now) - pd.Timedelta(hours=hours)]
    return (
        recent.set_index("minute")[["temperature", "humidity"]]
        .resample("5min")
        .mean()
        .dropna()
        .reset_index()
    )


BINS_SQL = """
    WITH r AS (
        SELECT temperature, humidity,
               least(extract(epoch FROM lead(reading_time) OVER (ORDER BY reading_time)
                                        - reading_time)::float8,
                     %(cap)s) AS sec
        FROM sensor_readings
        WHERE reading_time > now() - interval '14 days'
    )
    SELECT floor(temperature / %(tstep)s) * %(tstep)s AS t_bin,
           floor(humidity / %(hstep)s) * %(hstep)s    AS h_bin,
           sum(sec) / 3600                              AS hours
    FROM r
    WHERE sec IS NOT NULL
    GROUP BY 1, 2
"""


@st.cache_data(ttl=600)
def load_bins() -> pd.DataFrame:
    """Time spent in each (T_STEP x H_STEP) cell over the last 14 days.
    Columns: t_bin, h_bin (left bin edges), hours. Empty cells are absent."""
    params = {"cap": GAP_CAP_S, "tstep": T_STEP, "hstep": H_STEP}
    with get_conn() as conn:
        rows = conn.execute(BINS_SQL, params).fetchall()
    return pd.DataFrame(rows, columns=["t_bin", "h_bin", "hours"])
