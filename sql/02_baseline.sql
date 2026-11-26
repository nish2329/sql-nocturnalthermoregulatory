-- 02_baseline.sql
-- Personal baseline: median and MAD of skin temperature and heart rate for each
-- participant and clock hour of the night. Median/MAD so the surges we're looking
-- for don't drag the baseline up.

SET client_min_messages = warning;

DROP TABLE IF EXISTS baselines CASCADE;

CREATE TABLE baselines AS
WITH hourly AS (
  SELECT participant_id,
         EXTRACT(HOUR FROM ts) AS hour_of_night,
         skin_temp, heart_rate
  FROM clean_readings
),
med AS (
  SELECT participant_id, hour_of_night,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY skin_temp)  AS temp_med,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY heart_rate) AS hr_med
  FROM hourly
  GROUP BY participant_id, hour_of_night
)
SELECT h.participant_id, h.hour_of_night, m.temp_med, m.hr_med,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(h.skin_temp  - m.temp_med)) AS temp_mad,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(h.heart_rate - m.hr_med))   AS hr_mad,
       COUNT(*) AS n_readings
FROM hourly h
JOIN med m USING (participant_id, hour_of_night)
GROUP BY h.participant_id, h.hour_of_night, m.temp_med, m.hr_med;

CREATE UNIQUE INDEX ON baselines (participant_id, hour_of_night);
