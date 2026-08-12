-- Reconstructed schema (the original was lost with the laptop).
-- CHECK bounds are the BME280 datasheet operating range, not climate
-- expectations: they catch garbage (0 on I2C failure, raw Pa ~101325)
-- without rejecting honest readings, e.g. ~900 hPa station pressure
-- at high altitude.
CREATE TABLE sensor_readings (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reading_time timestamptz NOT NULL DEFAULT now(),
    temperature  real NOT NULL CHECK (temperature BETWEEN -40 AND 85),
    humidity     real NOT NULL CHECK (humidity BETWEEN 0 AND 100),
    pressure     real NOT NULL CHECK (pressure BETWEEN 300 AND 1100)
);

-- Every query walks the time axis (ORDER BY reading_time DESC LIMIT,
-- dashboard range scans), so this is the one index we need.
CREATE INDEX sensor_readings_time_idx ON sensor_readings (reading_time DESC);
