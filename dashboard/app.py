from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from climate import distribution_figure, phase_figure
from config import DASHBOARD_TZ
from daily import daily_figure
from data import latest, load_bins, load_daily, trail

st.set_page_config(page_title="Weather Station", page_icon="🌡️", layout="wide")

st.title("Weather Station")

cur = latest()
if cur is None:
    st.warning("No readings in the database yet.")
    st.stop()

age = datetime.now(UTC) - cur.reading_time
# zoneinfo reads the image's system tzdata (python:3.13-slim ships it).
local = cur.reading_time.astimezone(ZoneInfo(DASHBOARD_TZ))
time_col, t_col, h_col = st.columns(3)
fmt = "%H:%M:%S" if local.date() == datetime.now(local.tzinfo).date() else "%b %d, %H:%M:%S"
time_col.metric("Last reading", local.strftime(fmt))
time_col.caption(f"{int(age.total_seconds())} s ago")
t_col.metric("Temperature", f"{cur.temperature:.1f} °C")
h_col.metric("Humidity", f"{cur.humidity:.0f} %")
if age > timedelta(minutes=5):
    st.warning("No new readings for over 5 minutes: the sensor may be down.")

daily, now = load_daily()
st.plotly_chart(daily_figure(daily, now))

bins = load_bins()
phase_col, dist_col = st.columns(2)
phase_col.plotly_chart(phase_figure(bins, trail(daily, now), cur))
dist_col.plotly_chart(distribution_figure(bins, cur))
