#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

#include "config.h" // ssid, password, serverURL, sensorToken; copy config_example.h -> config.h
#include "certs.h"  // LE_ROOTS: Let's Encrypt ISRG Root X1 + X2

Adafruit_BME280 bme; // I2C, default ESP32 pins: GPIO21 (SDA), GPIO22 (SCL)

unsigned long delayTime;

void setup() {
    Serial.begin(9600);
    while(!Serial);
    Serial.println(F("BME280 test"));

    unsigned status;
    status = bme.begin(0x76); // 0x76 is the default I2C address of the BME280 (some boards use 0x77)
    if (!status) {
        Serial.println("Could not find a valid BME280 sensor, check wiring, address, sensor ID!");
        Serial.print("SensorID was: 0x"); Serial.println(bme.sensorID(),16);
        while (1) delay(10);
    }
    
    Serial.println("-- Default Test --");
    delayTime = 60000; // weather changes on a scale of minutes; 60 s is plenty

    Serial.println();

    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }
  Serial.println(" Connected!");

    // TLS cert validation needs the current time; block until NTP sets it
    configTime(0, 0, "pool.ntp.org");
    Serial.print("Syncing time");
    while (time(nullptr) < 1000000000) { // anything past 2001 means NTP responded
        delay(200);
        Serial.print(".");
    }
    Serial.println(" Synced!");
}

void loop() { 
    printValues();
    delay(delayTime);
}

void printValues() {
    float temp = bme.readTemperature();
    float hum = bme.readHumidity();
    float pres = bme.readPressure() / 100.0F;

    // Create JSON payload
    StaticJsonDocument<200> doc;
    doc["temp"] = temp;
    doc["hum"] = hum;
    doc["pres"] = pres;
    String jsonPayload;
    serializeJson(doc, jsonPayload);

    WiFiClientSecure client;
    client.setCACert(LE_ROOTS);
    HTTPClient http;
    http.begin(client, serverURL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + sensorToken);
    int httpCode = http.POST(jsonPayload);
    String response = http.getString();
    http.end();

    Serial.printf("Response: %d, %s\n", httpCode, response.c_str());
    if (httpCode < 0) Serial.printf("HTTP error: %s\n", http.errorToString(httpCode).c_str());
  }