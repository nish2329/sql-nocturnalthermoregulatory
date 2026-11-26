-- 03_score.sql
-- Robust z-scores against the personal baseline, then a trailing 10-minute
-- window: mean temperature z and max heart-rate rise over that window.

SET client_min_messages = warning;

DROP TABLE IF EXISTS scored_readings CASCADE;

CREATE TABLE scored_readings AS
WITH z AS (
  SELECT c.participant_id,
         c.sleep_period_id,
         c.ts,
         c.skin_temp,
         c.heart_rate,
         b.temp_med,
         b.hr_med,
         -- 1.4826 * MAD ~ SD for normal data; floor avoids divide-by-~0
         (c.skin_temp - b.temp_med) / GREATEST(1.4826 * b.temp_mad, 0.05) AS temp_z_raw,
         c.heart_rate - b.hr_med                                          AS hr_delta_raw
  FROM clean_readings c
  JOIN baselines b
    ON b.participant_id = c.participant_id
   AND b.hour_of_night  = EXTRACT(HOUR FROM c.ts)
)
SELECT participant_id, sleep_period_id, ts, skin_temp, heart_rate, temp_med, hr_med,
       temp_z_raw, hr_delta_raw,
       AVG(temp_z_raw)   OVER w AS temp_z,
       MAX(hr_delta_raw) OVER w AS hr_delta,
       COUNT(*)          OVER w AS n_in_window
FROM z
WINDOW w AS (PARTITION BY sleep_period_id ORDER BY ts
             RANGE BETWEEN INTERVAL '9 minutes' PRECEDING AND CURRENT ROW);

CREATE INDEX ON scored_readings (sleep_period_id, ts);
ANALYZE scored_readings;
