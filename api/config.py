import os

# Read at import time: a missing variable fails at startup,
# not on the first request.
DATABASE_URL = os.environ["DATABASE_URL"]
SENSOR_TOKEN = os.environ["SENSOR_TOKEN"]
