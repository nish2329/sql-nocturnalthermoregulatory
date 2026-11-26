-- 00_schema.sql
-- Raw tables. Everything downstream is derived from these.

SET client_min_messages = warning;

DROP TABLE IF EXISTS sim_truth, raw_readings, sleep_periods, participants CASCADE;

CREATE TABLE participants (
    participant_id text PRIMARY KEY,
    age_group      text NOT NULL CHECK (age_group IN ('18-34', '45-55'))
);

CREATE TABLE sleep_periods (
    sleep_period_id text PRIMARY KEY,
    participant_id  text NOT NULL REFERENCES participants,
    sleep_start     timestamp NOT NULL,
    sleep_end       timestamp NOT NULL CHECK (sleep_end > sleep_start)
);

-- One row per minute from the ring. Values are as recorded, including junk.
CREATE TABLE raw_readings (
    participant_id text NOT NULL REFERENCES participants,
    ts             timestamp NOT NULL,
    skin_temp      real,
    heart_rate     smallint
);

-- Only exists for the synthetic data: what was actually injected.
-- Used by python/06_check_against_truth.py, never by the detector.
CREATE TABLE sim_truth (
    participant_id  text NOT NULL,
    sleep_period_id text NOT NULL,
    kind            text NOT NULL,
    start_ts        timestamp NOT NULL,
    end_ts          timestamp NOT NULL
);
