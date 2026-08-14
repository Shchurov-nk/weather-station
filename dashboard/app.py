from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from config import DASHBOARD_TZ
from db import get_conn

st.set_page_config(page_title="Weather Station", page_icon="🌡️", layout="wide")

# Aggregation and the UTC -> local conversion both happen in SQL: the db
# walks sensor_readings_time_idx and ships ~720 rows, not 12 h of raw ones.
READINGS_SQL = """
    SELECT date_trunc('minute', reading_time AT TIME ZONE %(tz)s) AS minute,
           avg(temperature) AS temperature,
           avg(humidity)    AS humidity
    FROM sensor_readings
    WHERE reading_time > now() - interval '12 hours'
    GROUP BY minute
    ORDER BY minute
"""


@st.cache_data(ttl=60)
def load_readings() -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute(READINGS_SQL, {"tz": DASHBOARD_TZ}).fetchall()
    return pd.DataFrame(rows, columns=["minute", "temperature", "humidity"])


def last_reading_at() -> datetime | None:
    # Uncached on purpose: the whole point of the metric is liveness,
    # and max() on the DESC index is effectively free.
    with get_conn() as conn:
        return conn.execute("SELECT max(reading_time) FROM sensor_readings").fetchone()[0]


def line_chart(df: pd.DataFrame, column: str, title: str, unit: str, color: str) -> None:
    # px.line draws straight through gaps (sensor downtime); acceptable
    # for v1, a real gap treatment can come with the range selector.
    fig = px.line(df, x="minute", y=column, color_discrete_sequence=[color])
    fig.update_traces(line_width=2, hovertemplate="%{x|%H:%M} — %{y:.1f} " + unit)
    fig.update_layout(
        title=title,
        xaxis_title=None,
        yaxis_title=unit,
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
    )
    st.plotly_chart(fig, use_container_width=True)


st.title("Weather Station")

last = last_reading_at()
if last is None:
    st.warning("No readings in the database yet.")
    st.stop()

age = int((datetime.now(UTC) - last).total_seconds())
st.metric("Last reading", f"{age} s ago")

df = load_readings()
line_chart(df, "temperature", "Temperature, last 12 h (1-min avg)", "°C", "#e45756")
line_chart(df, "humidity", "Humidity, last 12 h (1-min avg)", "%", "#4c78a8")
