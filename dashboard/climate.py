"""Temperature x humidity charts over the 14-day time-weighted bins:
the phase plot (where the room spends its time, plus the recent path)
and the per-quantity distributions."""

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import H_COLOR, T_COLOR
from data import H_STEP, T_STEP, Latest

MARGIN = {"l": 40, "r": 20, "t": 50, "b": 40}
# Translucent grey -> saturated purple: sits on both Streamlit themes and
# stays clear of the red/blue used for temperature/humidity.
OCCUPANCY_SCALE = [
    [0.0, "rgba(150, 150, 150, 0.15)"],
    [0.5, "rgba(150, 100, 210, 0.55)"],
    [1.0, "rgba(110, 40, 190, 0.95)"],
]


def _no_data(fig: go.Figure) -> go.Figure:
    fig.add_annotation(
        text="no data", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False
    )
    return fig


def _hours_label(h: float) -> str:
    return f"{h:.1f} h" if h >= 1 else f"{h * 60:.0f} min"


def _hour_ticks(lo: float, hi: float) -> list[float]:
    # Colorbar ticks in hours on the log10 scale: decades when the range
    # spans several, 1-2-5 steps when it is narrow, and the ends themselves
    # when even that leaves no tick (a single bin).
    mults = (1,) if hi - lo >= 2 else (1, 2, 5)
    vals = [m * 10.0**k for k in range(math.floor(lo), math.ceil(hi) + 1) for m in mults]
    ticks = [v for v in vals if lo - 1e-9 <= math.log10(v) <= hi + 1e-9]
    return ticks or sorted({float(f"{10**lo:.2g}"), float(f"{10**hi:.2g}")})


def _occupancy(bins: pd.DataFrame) -> go.Heatmap:
    # Integer bin indices, so the full grid is exact whatever the float
    # edges round to; cells never visited stay NaN (blank, no hover).
    ti = (bins["t_bin"] / T_STEP).round().astype(int)
    hi = (bins["h_bin"] / H_STEP).round().astype(int)
    grid = (
        bins.assign(ti=ti, hi=hi)
        .pivot_table(index="hi", columns="ti", values="hours", aggfunc="sum")
        .reindex(index=np.arange(hi.min(), hi.max() + 1), columns=np.arange(ti.min(), ti.max() + 1))
    )
    hours = grid.to_numpy()
    # Occupancy is heavily skewed (most time in a few cells): log10 keeps
    # the rarely visited cells visible.
    z = np.log10(hours)
    ticks = _hour_ticks(np.nanmin(z), np.nanmax(z))
    text = np.vectorize(lambda h: "" if np.isnan(h) else _hours_label(h))(hours)
    # x0/dx rather than x/y arrays: with a single row or column plotly
    # can't infer the cell size from the coordinates.
    return go.Heatmap(
        x0=(ti.min() + 0.5) * T_STEP,
        dx=T_STEP,
        y0=(hi.min() + 0.5) * H_STEP,
        dy=H_STEP,
        z=z,
        text=text,
        hoverongaps=False,
        hovertemplate="%{x:.2f} °C, %{y:.0f} %<br>%{text}<extra></extra>",
        colorscale=OCCUPANCY_SCALE,
        colorbar={
            "title": {"text": "time"},
            "tickvals": [math.log10(v) for v in ticks],
            "ticktext": [f"{v:g} h" for v in ticks],
        },
    )


def phase_figure(bins: pd.DataFrame, trail: pd.DataFrame, cur: Latest) -> go.Figure:
    """Humidity vs temperature: 14-day occupancy heatmap, the last-12h
    path fading with age, and the current reading on top."""
    bins = bins[bins["hours"] > 0]  # zero-length cells (duplicate timestamps) break log10
    fig = go.Figure()
    fig.update_layout(
        title="Temperature × humidity (14 days, last 12 h path)",
        xaxis_title="°C",
        yaxis_title="%",
        showlegend=False,
        margin=MARGIN,
    )
    if bins.empty and trail.empty:
        return _no_data(fig)

    ts, hs = [cur.temperature], [cur.humidity]
    if not bins.empty:
        fig.add_trace(_occupancy(bins))
        ts += [bins["t_bin"].min(), bins["t_bin"].max() + T_STEP]
        hs += [bins["h_bin"].min(), bins["h_bin"].max() + H_STEP]
    if not trail.empty:
        # Fade by age within the 12 h window rather than by rank, so a gap
        # in the data shows as a jump in brightness too.
        age = (trail["minute"] - trail["minute"].max()) / pd.Timedelta(hours=12)
        fig.add_trace(
            go.Scatter(
                x=trail["temperature"],
                y=trail["humidity"],
                mode="markers",
                marker={"color": "black", "size": 6, "opacity": (0.9 + 0.85 * age).clip(lower=0.05)},
                customdata=trail["minute"].dt.strftime("%H:%M"),
                hovertemplate="%{customdata}<br>%{x:.1f} °C, %{y:.0f} %<extra></extra>",
            )
        )
        ts += [trail["temperature"].min(), trail["temperature"].max()]
        hs += [trail["humidity"].min(), trail["humidity"].max()]
    fig.add_trace(
        go.Scatter(
            x=[cur.temperature],
            y=[cur.humidity],
            mode="markers",
            marker={"color": "black", "size": 14, "line": {"color": "white", "width": 2}},
            hovertemplate="now<br>%{x:.1f} °C, %{y:.0f} %<extra></extra>",
        )
    )
    fig.update_xaxes(range=[min(ts) - T_STEP, max(ts) + T_STEP])
    fig.update_yaxes(range=[min(hs) - H_STEP, max(hs) + H_STEP])
    return fig


def _shares(bins: pd.DataFrame, col: str, step: float, unit: str, color: str) -> go.Bar:
    share = bins.groupby(col)["hours"].sum() / bins["hours"].sum() * 100
    # Bars at bin centres: the edge alone would put the "now" line half a
    # bin off from the bar it belongs to.
    return go.Bar(
        x=share.index + step / 2,
        y=share.to_numpy(),
        width=step,
        marker_color=color,
        opacity=0.6,
        customdata=np.column_stack([share.index, share.index + step]),
        hovertemplate="%{customdata[0]:g}–%{customdata[1]:g} " + unit + ": %{y:.1f} %<extra></extra>",
    )


def distribution_figure(bins: pd.DataFrame, cur: Latest) -> go.Figure:
    """Share of the last 14 days spent in each temperature / humidity bin,
    with the current values marked."""
    bins = bins[bins["hours"] > 0]  # an all-zero total would divide by zero
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Temperature", "Humidity"))
    fig.update_layout(
        title="Distribution, last 14 days (share of time)",
        showlegend=False,
        bargap=0,
        margin=MARGIN,
    )
    if bins.empty:
        return _no_data(fig)

    fig.add_trace(_shares(bins, "t_bin", T_STEP, "°C", T_COLOR), row=1, col=1)
    fig.add_trace(_shares(bins, "h_bin", H_STEP, "%", H_COLOR), row=1, col=2)
    fig.update_xaxes(title_text="°C", row=1, col=1)
    fig.update_xaxes(title_text="%", row=1, col=2)
    fig.update_yaxes(title_text="share of time, %", row=1, col=1)
    # After the traces and with explicit row/col: otherwise add_vline
    # draws the line on every subplot.
    for col, label, value, color in (
        (1, f"{cur.temperature:.1f} °C", cur.temperature, T_COLOR),
        (2, f"{cur.humidity:.0f} %", cur.humidity, H_COLOR),
    ):
        fig.add_vline(
            x=value,
            row=1,
            col=col,
            line={"color": color, "dash": "dash", "width": 2},
            annotation_text=f"now {label}",
            annotation_font_color=color,
        )
    return fig
