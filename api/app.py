import logging
import secrets

from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError

from config import SENSOR_TOKEN
from db import get_conn
from schemas import SensorReading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def token_ok(header):
    if not header or not header.startswith("Bearer "):
        return False
    # Constant-time comparison: a plain == leaks the match length via timing.
    return secrets.compare_digest(header.removeprefix("Bearer "), SENSOR_TOKEN)


@app.route('/sensor', methods=['POST'])
def add_sensor_data():
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"error": "unauthorized"}), 401

    try:
        reading = SensorReading.model_validate(request.get_json(silent=True))
    except ValidationError as e:
        return jsonify({"error": "validation failed",
                        "detail": e.errors(include_url=False)}), 422

    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO sensor_readings (temperature, humidity, pressure) VALUES (%s, %s, %s)",
                (reading.temp, reading.hum, reading.pres),
            )
        return jsonify({"status": "success"}), 201
    except Exception:
        # Full traceback to the logs, nothing internal to the client.
        logger.exception("insert failed")
        return jsonify({"error": "internal server error"}), 500


@app.route('/table')
def display_data():
    try:
        query = """
            SELECT reading_time::timestamp(0), temperature, humidity, pressure
            FROM sensor_readings
            ORDER BY reading_time DESC
            LIMIT 15
        """
        with get_conn() as conn:
            records = conn.execute(query).fetchall()
        return render_template('table.html', records=records)
    except Exception:
        logger.exception("table query failed")
        return "internal server error", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
