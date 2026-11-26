-- 01_clean.sql
-- Drop impossible values, attach each reading to its sleep period, mark gaps,
-- and keep only nights with enough valid data.

SET client_min_messages = warning;

CREATE INDEX IF NOT EXISTS raw_readings_pid_ts ON raw_readings (participant_id, ts);
ANALYZE raw_readings;

DROP TABLE IF EXISTS clean_readings, valid_nights CASCADE;

-- Readings inside a sleep period with physiologically possible values.
CREATE TEMP TABLE in_range AS
SELECT r.participant_id,
       s.sleep_period_id,
       r.ts,
       r.skin_temp,
       r.heart_rate
FROM raw_readings r
JOIN sleep_periods s
  ON s.participant_id = r.participant_id
 AND r.ts >= s.sleep_start
 AND r.ts <  s.sleep_end
WHERE r.skin_temp  BETWEEN 20 AND 42
  AND r.heart_rate BETWEEN 30 AND 200;

-- Ring-off periods read as cold but "valid" skin temperature (20-28 C).
-- Those are removed per night: anything more than 4 C below the night's median.
CREATE TEMP TABLE night_med AS
SELECT sleep_period_id,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY skin_temp) AS night_temp_med
FROM in_range
GROUP BY sleep_period_id;

CREATE TEMP TABLE kept AS
SELECT i.*
FROM in_range i
JOIN night_med n USING (sleep_period_id)
WHERE i.skin_temp > n.night_temp_med - 4;

-- Gap marking: minutes since the previous valid reading in the same night.
CREATE TEMP TABLE with_gaps AS
SELECT k.*,
       EXTRACT(EPOCH FROM ts - LAG(ts) OVER (PARTITION BY sleep_period_id ORDER BY ts)) / 60
           AS minutes_since_prev
FROM kept k;

-- A night counts if it has >= 5 hours of valid minutes.
CREATE TABLE valid_nights AS
SELECT s.sleep_period_id,
       s.participant_id,
       s.sleep_start,
       s.sleep_end,
       COUNT(*)                                         AS valid_minutes,
       COUNT(*) FILTER (WHERE g.minutes_since_prev > 5) AS n_gaps
FROM with_gaps g
JOIN sleep_periods s USING (sleep_period_id)
GROUP BY s.sleep_period_id, s.participant_id, s.sleep_start, s.sleep_end
HAVING COUNT(*) >= 300;

CREATE TABLE clean_readings AS
SELECT g.participant_id,
       g.sleep_period_id,
       g.ts,
       g.skin_temp,
       g.heart_rate,
       g.minutes_since_prev
FROM with_gaps g
JOIN valid_nights v USING (sleep_period_id);

CREATE INDEX ON clean_readings (participant_id, ts);
ANALYZE clean_readings;
