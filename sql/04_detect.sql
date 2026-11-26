-- 04_detect.sql
-- Event rule + gaps-and-islands merge, wrapped in a function so the robustness
-- scripts can re-run it at other thresholds.

SET client_min_messages = warning;

DROP FUNCTION IF EXISTS detect_events(double precision, double precision, interval) CASCADE;

CREATE FUNCTION detect_events(temp_thr double precision DEFAULT 2.0,
                              hr_thr   double precision DEFAULT 8,
                              merge_gap interval       DEFAULT INTERVAL '15 minutes')
RETURNS TABLE (participant_id  text,
               sleep_period_id text,
               event_id        bigint,
               start_ts        timestamp,
               end_ts          timestamp,
               duration_min    double precision,
               peak_temp_z     double precision,
               peak_hr_delta   double precision)
LANGUAGE sql STABLE AS $$
WITH flagged AS (
  SELECT participant_id, sleep_period_id, ts, temp_z_raw, hr_delta_raw
  FROM scored_readings
  WHERE temp_z > temp_thr AND hr_delta >= hr_thr
    AND n_in_window >= 6            -- need most of the 10-minute window present
),
marked AS (
  SELECT f.*,
         CASE WHEN LAG(ts) OVER w IS NULL
                OR ts - LAG(ts) OVER w > merge_gap
              THEN 1 ELSE 0 END AS new_event
  FROM flagged f
  WINDOW w AS (PARTITION BY sleep_period_id ORDER BY ts)
),
numbered AS (
  SELECT m.*,
         SUM(new_event) OVER (PARTITION BY sleep_period_id ORDER BY ts) AS event_id
  FROM marked m
)
SELECT participant_id, sleep_period_id, event_id,
       MIN(ts), MAX(ts),
       EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) / 60 + 1,
       MAX(temp_z_raw), MAX(hr_delta_raw)
FROM numbered
GROUP BY participant_id, sleep_period_id, event_id
$$;

DROP TABLE IF EXISTS events CASCADE;
CREATE TABLE events AS SELECT * FROM detect_events(2.0, 8, INTERVAL '15 minutes');
