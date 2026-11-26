-- 05_person_nights.sql
-- One row per valid night: event count, hours slept, bedtime, season, age group.
-- This is the table the model is fitted on.

SET client_min_messages = warning;

DROP FUNCTION IF EXISTS person_nights(double precision, double precision, interval) CASCADE;

CREATE FUNCTION person_nights(temp_thr double precision DEFAULT 2.0,
                              hr_thr   double precision DEFAULT 8,
                              merge_gap interval       DEFAULT INTERVAL '15 minutes')
RETURNS TABLE (participant_id  text,
               sleep_period_id text,
               age_group       text,
               n_events        bigint,
               hours_slept     double precision,
               bedtime_h       double precision,
               season          text)
LANGUAGE sql STABLE AS $$
WITH ev AS (
  SELECT sleep_period_id, COUNT(*) AS n_events
  FROM detect_events(temp_thr, hr_thr, merge_gap)
  GROUP BY sleep_period_id
)
SELECT v.participant_id,
       v.sleep_period_id,
       p.age_group,
       COALESCE(ev.n_events, 0),
       v.valid_minutes / 60.0,
       -- bedtime as hours after 18:00, so 23:30 -> 5.5 and 01:00 -> 7.0
       MOD(EXTRACT(EPOCH FROM v.sleep_start::time)::numeric / 3600 + 6, 24)::double precision,
       CASE WHEN EXTRACT(MONTH FROM v.sleep_start) IN (12, 1, 2) THEN 'winter'
            WHEN EXTRACT(MONTH FROM v.sleep_start) IN (3, 4, 5)  THEN 'spring'
            WHEN EXTRACT(MONTH FROM v.sleep_start) IN (6, 7, 8)  THEN 'summer'
            ELSE 'autumn' END
FROM valid_nights v
JOIN participants p USING (participant_id)
LEFT JOIN ev USING (sleep_period_id)
$$;

DROP TABLE IF EXISTS person_night_summary CASCADE;
CREATE TABLE person_night_summary AS SELECT * FROM person_nights();
