# Home weather station in python. Simple and cheap
## Hardware
- Old laptop as a server
- ESP32 microcontroller. To send data from BME280 to server
- BME280 sensor. To measure temperature, humidity, and pressure
## Software
- Ubuntu server 24.04
- Postgres database. To store data from sensor
- Flask app. To communicate with database and display a webpage with last sensor readings
- Gunicorn. WSGI server to communicate with ESP32 using http
## How does this work
A BME280 sensor is pluged into a power source. It has wifi connection.  
This sensor is running a programm in a loop.  
This programm on ESP32 is simply:
1) Measure temperature, humidity and pressure
2) Use wifi to send a POST http request to a server with json, containing measurements.
3) Wait for 6 seconds
4) Go back to step one

On a server side, data from json is handled by Gunicorn running Flask app. This Flask app:
1) Saves measurements from json to a databse. I also save the time of inserting values to a database which is not really accurate, because I measure data slightly earlier, that I record them to database. But this accuracy is fine to me.
2) Displays last readings in a html table

## How to set everything up
### This section is not finished yet

To run gunicorn:  
```bash
gunicorn --workers 5 --bind 0.0.0.0:8000 app:app --daemon --reload
```
