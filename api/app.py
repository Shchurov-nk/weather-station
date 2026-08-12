import os

from flask import Flask, request, jsonify, render_template
import psycopg2

# Single source of config that works the same locally, in compose and in CI.
DATABASE_URL = os.environ["DATABASE_URL"]

app = Flask(__name__)


@app.route('/sensor', methods=['POST'])
def add_sensor_data():
    try:
        data = request.get_json()
        temp = data['temp']
        hum = data['hum']
        pres = data['pres']
        values = (temp, hum, pres)
        query = "INSERT INTO sensor_readings (temperature, humidity, pressure) VALUES (%s, %s, %s)"
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()
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
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                records = cur.fetchall()
        return render_template('table.html', records=records)
    except Exception as e:
        return f"Error fetching data: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
