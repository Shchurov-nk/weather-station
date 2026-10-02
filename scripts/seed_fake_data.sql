-- Fake readings for local dashboard work: 14 days ending now, daily
-- sinusoid plus a little noise, with two deliberate defects (see below).
-- Replaces anything in the last 15 days. Run against a local db only:
--   docker compose exec -T db psql -U weather weather < scripts/seed_fake_data.sql
--
-- One statement on purpose: it is atomic on its own (no BEGIN/COMMIT here),
-- so it can also be tried inside BEGIN; ... ROLLBACK; without side effects.
WITH
-- Clear the window first so a re-run doesn't stack a second copy.
cleared AS (
    DELETE FROM sensor_readings WHERE reading_time > now() - interval '15 days'
),
-- Normal operation: the firmware's 6 s step, minus the two segments below.
normal AS (
    SELECT t, 0 AS t_shift
    FROM generate_series(now() - interval '14 days', now(), interval '6 seconds') AS t
    WHERE NOT (t >= now() - interval '7 days' AND t < now() - interval '5 days')
      -- Sensor down for 6 h, 24..30 h ago: always inside the 3 local days
      -- the daily chart shows, so its lines must break here.
      AND NOT (t >= now() - interval '30 hours' AND t < now() - interval '24 hours')
),
-- Flaky contact, 7..5 days ago: readings every 1 s and 6 °C hotter. It is
-- 2 days of time but 6x the rows, so a count-weighted heatmap would make
-- this hot spot look like 12 days; the time-weighted one must show 2.
burst AS (
    SELECT t, 6 AS t_shift
    FROM generate_series(now() - interval '7 days',
                         now() - interval '5 days' - interval '1 second',
                         interval '1 second') AS t
)
INSERT INTO sensor_readings (reading_time, temperature, humidity, pressure)
SELECT t,
       22 + t_shift + 5 * sin(2 * pi() * extract(epoch FROM t) / 86400) + random(),
       55 - 10 * sin(2 * pi() * extract(epoch FROM t) / 86400) + 2 * random(),
       1005 + 3 * random()
FROM (SELECT * FROM normal UNION ALL SELECT * FROM burst) AS s;
