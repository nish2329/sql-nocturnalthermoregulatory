"""
Generate a synthetic ring-wearable dataset and load it into PostgreSQL.

The real data can't be shared, so this script builds a stand-in with the same
shape: per-minute skin temperature and heart rate during sleep, one row per
sleep period, and an age group per participant.

What's simulated
----------------
* Person-level baselines for skin temperature and heart rate.
* A within-night profile: skin temperature climbs after sleep onset and
  plateaus; heart rate drifts down across the night.
* AR(1) noise on both signals.
* Menstrual-cycle temperature shift (luteal phase) in the 18-34 group.
* Thermoregulatory events: a fast skin-temp rise with a heart-rate rise,
  decaying over 10-25 minutes. Rate is higher in the 45-55 group and varies
  between people (gamma-distributed).
* Things that look like events but aren't:
    - "warm arousals" (waking up under heavy bedding): a smaller temp + HR bump
    - alcohol nights: HR and temp elevated for most of the night
    - temp-only bumps (room/bedding) and HR-only bumps (movement, dreams)
* Data problems: dropped minutes, short nights, physiologically impossible
  values (ring off, sensor glitches).

Ground truth for injected events and artifacts goes into sim_truth so the
detector can be checked against it. The pipeline itself never reads that table.

Usage
-----
    python python/00_generate_synthetic.py            # full dataset (~600 people)
    python python/00_generate_synthetic.py --demo     # small demo (~40 people)
    python python/00_generate_synthetic.py --csv-out data/demo   # also write CSVs
"""

import argparse
import gzip
import io
import os
from datetime import datetime, timedelta

import numpy as np
import psycopg2

from db import connect

START_DATE = datetime(2025, 1, 6)


def ar1(rng, n, phi, sd):
    """AR(1) noise with stationary sd `sd`."""
    eps = rng.normal(0, sd * np.sqrt(1 - phi**2), n)
    x = np.empty(n)
    x[0] = rng.normal(0, sd)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def surge(n, t0, rise, decay, amp):
    """Fast rise over `rise` minutes, exponential decay with time constant `decay`."""
    t = np.arange(n) - t0
    out = np.zeros(n)
    up = (t >= 0) & (t < rise)
    out[up] = amp * (t[up] + 1) / rise
    down = t >= rise
    out[down] = amp * np.exp(-(t[down] - rise) / decay)
    return out


def simulate_participant(rng, pid, group, n_nights):
    temp_base = rng.normal(34.4, 0.6)
    hr_base = rng.normal(60 if group == "45-55" else 58, 6)
    # person-level event rate (events per 7.5h night)
    mean_rate = 0.62 if group == "45-55" else 0.16
    shape = 1.5
    person_rate = rng.gamma(shape, mean_rate / shape)
    cycle_offset = rng.integers(0, 28)
    alcohol_p = rng.uniform(0.02, 0.10)

    periods, readings, truth = [], [], []
    day_idx = int(rng.integers(0, 365))          # stagger start dates across the year
    for night in range(n_nights):
        day_idx += 1 + int(rng.random() < 0.35)  # not every night is recorded
        day = START_DATE + timedelta(days=day_idx)
        onset_min = int(rng.normal(23.3 * 60, 50))          # minutes after midnight of `day`
        dur = int(np.clip(rng.normal(7.3 * 60, 55), 150, 600))
        if rng.random() < 0.05:                              # some short nights
            dur = int(rng.uniform(150, 290))
        start = day + timedelta(minutes=onset_min)
        sp_id = f"{pid}-{night:03d}"
        periods.append((sp_id, pid, start, start + timedelta(minutes=dur)))

        n = dur
        m = np.arange(n)
        # within-night profile
        temp = temp_base + 0.9 * (1 - np.exp(-m / 70)) + ar1(rng, n, 0.97, 0.18)
        hr = hr_base + 4 * np.exp(-m / 90) - 3 * (m / n) + ar1(rng, n, 0.9, 2.2)

        if group == "18-34":
            phase = (day_idx + cycle_offset) % 28
            if phase >= 14:                                  # luteal phase
                temp += 0.30
                hr += 2.0

        if rng.random() < alcohol_p:
            temp += rng.uniform(0.1, 0.35)
            hr += rng.uniform(3, 8)
            truth.append((pid, sp_id, "alcohol_night", start, start + timedelta(minutes=n)))

        def place(kind, k):
            for _ in range(k):
                t0 = int(rng.uniform(20, max(21, n - 30)))
                if kind == "thermo_event":
                    rise, decay = rng.integers(2, 6), rng.uniform(5, 10)
                    temp_amp, hr_amp = rng.uniform(1.0, 2.2), rng.uniform(10, 22)
                elif kind == "warm_arousal":
                    rise, decay = rng.integers(2, 5), rng.uniform(4, 9)
                    temp_amp, hr_amp = rng.uniform(0.5, 1.3), rng.uniform(6, 14)
                elif kind == "temp_only":
                    rise, decay = rng.integers(3, 8), rng.uniform(6, 15)
                    temp_amp, hr_amp = rng.uniform(0.6, 1.6), 0.0
                else:  # hr_only
                    rise, decay = rng.integers(1, 3), rng.uniform(2, 6)
                    temp_amp, hr_amp = 0.0, rng.uniform(10, 30)
                temp[:] += surge(n, t0, rise, decay, temp_amp)
                hr[:] += surge(n, t0, rise, decay * 0.7, hr_amp)
                length = int(rise + 2.5 * decay)
                truth.append((pid, sp_id, kind,
                              start + timedelta(minutes=t0),
                              start + timedelta(minutes=min(n - 1, t0 + length))))

        hours = n / 60
        place("thermo_event", rng.poisson(person_rate * hours / 7.5))
        place("warm_arousal", rng.poisson(0.12 * hours / 7.5))
        place("temp_only", rng.poisson(0.25 * hours / 7.5))
        place("hr_only", rng.poisson(0.8 * hours / 7.5))

        # data problems
        keep = rng.random(n) > 0.01                          # scattered dropouts
        if rng.random() < 0.15:                              # one longer gap
            g0 = int(rng.uniform(0, n - 40))
            keep[g0:g0 + int(rng.uniform(10, 40))] = False
        if rng.random() < 0.03:                              # ring off for a while
            g0 = int(rng.uniform(0, n - 60))
            temp[g0:g0 + 60] = rng.uniform(18, 24)
        glitch = rng.random(n) < 0.002
        temp[glitch] = rng.choice([0.0, 45.5, 51.0], glitch.sum())
        hglitch = rng.random(n) < 0.002
        hr[hglitch] = rng.choice([0, 255, 220], hglitch.sum())

        ts = [start + timedelta(minutes=int(i)) for i in m[keep]]
        for t, a, b in zip(ts, temp[keep], hr[keep]):
            readings.append((pid, t, round(float(a), 3), int(round(b))))

    return periods, readings, truth


def to_copy_buffer(rows):
    buf = io.StringIO()
    for r in rows:
        buf.write("\t".join("\\N" if v is None else (v.isoformat(sep=" ") if isinstance(v, datetime) else str(v)) for v in r))
        buf.write("\n")
    buf.seek(0)
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="small dataset (~40 participants)")
    ap.add_argument("--seed", type=int, default=20251125)
    ap.add_argument("--csv-out", help="also write gzipped CSVs to this folder")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    n_old, n_young = (10, 30) if args.demo else (150, 450)
    participants = [(f"P{i:04d}", "45-55") for i in range(n_old)] + \
                   [(f"P{i:04d}", "18-34") for i in range(n_old, n_old + n_young)]

    conn = connect()
    cur = conn.cursor()
    with open(os.path.join(os.path.dirname(__file__), "..", "sql", "00_schema.sql")) as f:
        cur.execute(f.read())
    cur.execute("INSERT INTO participants VALUES " + ",".join(["(%s,%s)"] * len(participants)),
                [v for p in participants for v in p])

    csv = None
    if args.csv_out:
        os.makedirs(args.csv_out, exist_ok=True)
        csv = {name: gzip.open(os.path.join(args.csv_out, f"{name}.csv.gz"), "wt")
               for name in ("participants", "sleep_periods", "readings")}
        csv["participants"].write("participant_id,age_group\n")
        csv["participants"].writelines(f"{p},{g}\n" for p, g in participants)
        csv["sleep_periods"].write("sleep_period_id,participant_id,sleep_start,sleep_end\n")
        csv["readings"].write("participant_id,ts,skin_temp,heart_rate\n")

    total_nights = total_rows = 0
    for pid, group in participants:
        n_nights = int(np.clip(rng.normal(60 if group == "45-55" else 42, 12), 14, 110))
        periods, readings, truth = simulate_participant(rng, pid, group, n_nights)
        cur.copy_from(to_copy_buffer(periods), "sleep_periods")
        cur.copy_from(to_copy_buffer(readings), "raw_readings",
                      columns=("participant_id", "ts", "skin_temp", "heart_rate"))
        cur.copy_from(to_copy_buffer(truth), "sim_truth")
        if csv:
            csv["sleep_periods"].writelines(f"{a},{b},{c},{d}\n" for a, b, c, d in periods)
            csv["readings"].writelines(f"{a},{b},{c},{d}\n" for a, b, c, d in readings)
        total_nights += len(periods)
        total_rows += len(readings)

    conn.commit()
    if csv:
        for f in csv.values():
            f.close()
    print(f"participants={len(participants)} nights={total_nights} readings={total_rows}")


if __name__ == "__main__":
    main()
