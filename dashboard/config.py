import os

# Read at import time: a missing variable fails at startup,
# not on the first request.
DATABASE_URL = os.environ["DATABASE_URL"]
# reading_time is stored in UTC; charts show this zone instead.
DASHBOARD_TZ = os.environ["DASHBOARD_TZ"]
# One color per quantity, on every chart.
T_COLOR = "#e45756"
H_COLOR = "#4c78a8"
