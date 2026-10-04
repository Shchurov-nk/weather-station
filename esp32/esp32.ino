#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include "esp_task_wdt.h"

#include "config.h" // ssid, password, serverURL, sensorToken; copy config_example.h -> config.h
#include "certs.h"  // LE_ROOTS: Let's Encrypt ISRG Root X1 + X2

Adafruit_BME280 bme; // I2C, default ESP32 pins: GPIO21 (SDA), GPIO22 (SCL)

unsigned long delayTime;

volatile uint8_t lastDisconnectReason = 0;
unsigned long lastOkMs = 0;     // last 2xx from the server
unsigned long lastWifiUpMs = 0;
unsigned long lastRejoinMs = 0;

void onWiFiDisconnect(WiFiEvent_t event, WiFiEventInfo_t info) {
    uint8_t reason = info.wifi_sta_disconnected.reason;
    if (reason != WIFI_REASON_ASSOC_LEAVE) lastDisconnectReason = reason; // 8 = our own disconnect()
    Serial.printf("WiFi disconnected, reason %u\n", reason);
}

void setup() {
    Serial.begin(9600);
    while(!Serial);
    Serial.println(F("BME280 test"));
    Serial.printf("Reset reason: %d\n", (int)esp_reset_reason()); // see esp_reset_reason_t

    // Reset the board if setup() or a loop() iteration stalls for 90 s; the core feeds it before each loop() call
    esp_task_wdt_init(90, true);
    enableLoopWDT();

    unsigned status = 0;
    for (int i = 0; i < 5 && !status; i++) {
        status = bme.begin(0x76); // 0x76 is the default I2C address of the BME280 (some boards use 0x77)
        if (!status) delay(500);
    }
    if (!status) {
        Serial.println("Could not find a valid BME280 sensor, check wiring, address, sensor ID! Retrying in loop()");
        Serial.print("SensorID was: 0x"); Serial.println(bme.sensorID(),16);
    }
    
    Serial.println("-- Default Test --");
    delayTime = 6000;

    Serial.println();

    WiFi.onEvent(onWiFiDisconnect, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 30000UL)
    {
        delay(500);
        Serial.print(".");
    }
    Serial.println(WiFi.status() == WL_CONNECTED ? " Connected!" : " not yet, continuing");
}

void rejoinWiFi() {
    WiFi.disconnect();
    // status flips via the disconnect event; begin() is a no-op while it still reads WL_CONNECTED
    for (int i = 0; i < 20 && WiFi.status() == WL_CONNECTED; i++) delay(50);
    WiFi.begin(ssid, password);
    lastRejoinMs = millis();
}

void loop() { 
    unsigned long now = millis();
    bool wifiUp = WiFi.status() == WL_CONNECTED;
    if (wifiUp) lastWifiUpMs = now;

    if (now - lastOkMs > 600000UL) {
        Serial.println("No 2xx for 10 min, restarting");
        delay(100);
        ESP.restart();
    }
    if (!wifiUp && now - lastWifiUpMs > 30000UL && now - lastRejoinMs > 30000UL) {
        Serial.println("WiFi down for >30 s, rejoining");
        rejoinWiFi();
    } else if (wifiUp && now - lastOkMs > 180000UL && now - lastRejoinMs > 180000UL) {
        Serial.println("No 2xx for 3 min, rejoining");
        rejoinWiFi();
    }

    printValues(wifiUp);
    delay(delayTime);
}

// ctrl_meas (0xF4) mode bits drop back to sleep (0b00) if the sensor gets re-powered
bool bmeAwake() {
    Wire.beginTransmission(0x76);
    Wire.write(0xF4);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(0x76, 1) != 1) return false;
    return (Wire.read() & 0x03) == 0x03;
}

void printValues(bool wifiUp) {
    int httpCode = 0; // 0 = POST skipped
    unsigned long postMs = 0;
    String response;
    String err;

    if (!bmeAwake()) {
        Serial.println("BME280 lost/reset, re-init");
        bme.begin(0x76);
    } else {
        float temp = bme.readTemperature();
        float hum = bme.readHumidity();
        float pres = bme.readPressure() / 100.0F;

        // NaN fails every comparison
        if (!(temp >= -40 && temp <= 85 && hum >= 0 && hum <= 100 && pres >= 300 && pres <= 1100)) {
            Serial.printf("BME280 bad reading %.2f %.2f %.2f, re-init\n", temp, hum, pres);
            bme.begin(0x76);
        } else if (wifiUp) {
            // Create JSON payload
            StaticJsonDocument<200> doc;
            doc["temp"] = temp;
            doc["hum"] = hum;
            doc["pres"] = pres;
            String jsonPayload;
            serializeJson(doc, jsonPayload);

            WiFiClientSecure client;
            client.setCACert(LE_ROOTS);
            client.setHandshakeTimeout(15); // seconds
            HTTPClient http;
            http.setConnectTimeout(5000);
            http.setTimeout(5000);
            http.begin(client, serverURL);
            http.addHeader("Content-Type", "application/json");
            http.addHeader("Authorization", String("Bearer ") + sensorToken);
            unsigned long postStart = millis();
            httpCode = http.POST(jsonPayload);
            postMs = millis() - postStart;
            // getString() has no read timeout; the 201 body is not needed
            if (httpCode > 0 && httpCode != 201) response = http.getString();
            http.end();

            if (httpCode >= 200 && httpCode < 300) lastOkMs = millis();
            if (httpCode < 0) {
                char buf[100] = "";
                // 0 = no error recorded, >0 = socket fd from the last successful connect
                if (client.lastError(buf, sizeof(buf)) >= 0) buf[0] = 0;
                err = http.errorToString(httpCode) + " / " + buf;
            }
        }
    }

    Serial.printf("up=%lus heap=%u min=%u maxblk=%u rssi=%d wifi=%d code=%d post=%lums disc=%u err=%s body=%s\n",
        millis() / 1000, ESP.getFreeHeap(), ESP.getMinFreeHeap(), ESP.getMaxAllocHeap(),
        WiFi.RSSI(), (int)WiFi.status(), httpCode, postMs, lastDisconnectReason, err.c_str(), response.c_str());
}
