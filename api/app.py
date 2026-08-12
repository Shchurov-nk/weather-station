from flask import Flask, request, jsonify, render_template

from db import get_pool

app = Flask(__name__)


@app.route('/sensor', methods=['POST'])
def add_sensor_data():
    try:
        data = request.get_json()
        values = (data['temp'], data['hum'], data['pres'])
        query = "INSERT INTO sensor_readings (temperature, humidity, pressure) VALUES (%s, %s, %s)"
        # The pool hands out an open connection and commits on clean exit.
        with get_pool().connection() as conn:
            conn.execute(query, values)
        return jsonify({"status": "success"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/table')
def display_data():
    try:
        query = """
            SELECT reading_time::timestamp(0), temperature, humidity, pressure
            FROM sensor_readings
            ORDER BY reading_time DESC
            LIMIT 15
        """
        with get_pool().connection() as conn:
            records = conn.execute(query).fetchall()
        return render_template('table.html', records=records)
    except Exception as e:
        return f"Error fetching data: {str(e)}", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
