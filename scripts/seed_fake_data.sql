-- Fake readings for local dashboard work: 12 hours at a 30 s step, daily
-- sinusoid plus a little noise. Run against a local db only:
--   docker compose exec -T db psql -U weather weather < scripts/seed_fake_data.sql
INSERT INTO sensor_readings (reading_time, temperature, humidity, pressure)
SELECT t,
       22 + 5 * sin(2 * pi() * extract(epoch FROM t) / 86400) + random(),
       55 - 10 * sin(2 * pi() * extract(epoch FROM t) / 86400) + 2 * random(),
       1005 + 3 * random()
FROM generate_series(now() - interval '12 hours', now(), interval '30 seconds') AS t;
