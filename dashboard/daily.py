from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import H_COLOR, T_COLOR

# Same hue per quantity, older days fade: (day_offset, label, opacity, width).
DAYS = [(0, "Today", 1.0, 2), (1, "Yesterday", 0.45, 1.5), (2, "2 days ago", 0.2, 1.5)]
ROWS = [(1, "temperature", "°C", T_COLOR), (2, "humidity", "%", H_COLOR)]
# Longer than this without a 1-min average and the line breaks. Not every
# missing minute: a flaky sensor reporting every couple of minutes should
# still draw a line, not scattered invisible points.
GAP_H = 5 / 60


def _with_breaks(day: pd.DataFrame) -> pd.DataFrame:
    # A NaN row right after each gap's start: plotly breaks the line there
    # (connectgaps=False is the default) instead of drawing across downtime.
    starts = day.loc[day["hour"].diff().shift(-1) > GAP_H, "hour"]
    return pd.concat([day, pd.DataFrame({"hour": starts + 1 / 60})]).sort_values("hour")


def daily_figure(daily: pd.DataFrame, now: datetime) -> go.Figure:
    """Today, yesterday and the day before overlaid on one 0..24 h axis.
    Both rows share x (plotly `matches`), so a zoom on one zooms the other."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=["Temperature (1-min avg)", "Humidity (1-min avg)"],
    )
    for offset, label, opacity, width in DAYS:
        day = _with_breaks(daily[daily["day_offset"] == offset])
        # x is numeric hours, so hover gets HH:MM from customdata instead.
        minutes = (day["hour"] * 60).round().astype(int)
        hhmm = [f"{m // 60:02d}:{m % 60:02d}" for m in minutes]
        name = f"{label} ({now - timedelta(days=offset):%b %d})"
        for row, column, unit, color in ROWS:
            fig.add_trace(
                go.Scatter(
                    x=day["hour"],
                    y=day[column],
                    customdata=hhmm,
                    mode="lines",
                    name=name,
                    # One legend entry per day toggles it on both rows.
                    legendgroup=name,
                    showlegend=row == 1,
                    opacity=opacity,
                    line={"color": color, "width": width},
                    hovertemplate=f"%{{customdata}} — %{{y:.1f}} {unit}<extra>{name}</extra>",
                ),
                row=row,
                col=1,
            )
    for row, _, unit, _ in ROWS:
        fig.update_yaxes(title_text=unit, row=row, col=1)
    # After the traces: add_vline skips subplots that are still empty.
    now_h = now.hour + now.minute / 60
    line = {"dash": "dot", "color": "gray", "width": 1}
    fig.add_vline(x=now_h, line=line, row=1, col=1, annotation_text="now")
    fig.add_vline(x=now_h, line=line, row=2, col=1)
    fig.update_xaxes(
        range=[0, 24],
        tickvals=list(range(0, 25, 3)),
        ticktext=[f"{h:02d}:00" for h in range(0, 25, 3)],
    )
    fig.update_layout(
        height=600,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.06, "x": 0},
        margin={"l": 40, "r": 20, "t": 80, "b": 40},
    )
    return fig
