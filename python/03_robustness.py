"""
Robustness checks.

1. Threshold sensitivity: temperature and heart-rate thresholds each at
   -20%, -10%, 0, +10%, +20% (25 combinations). Detection is re-run in SQL
   (person_nights(temp_thr, hr_thr)) and the model is refitted each time.
2. Leave-one-participant-out: refit the model once per participant with that
   participant's nights removed.

Writes results/threshold_sensitivity.csv and results/leave_one_out.csv.
"""
import argparse
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from db import connect
from nbglmm import model_for

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
STEPS = [0.8, 0.9, 1.0, 1.1, 1.2]


def threshold_sweep():
    rows = []
    with connect() as conn:
        for ft in STEPS:
            for fh in STEPS:
                t_thr, h_thr = 2.0 * ft, 8 * fh
                df = pd.read_sql("SELECT * FROM person_nights(%s, %s)", conn, params=(t_thr, h_thr))
                fit, _ = model_for(df).fit()
                rr, lo, hi = fit.rate_ratio("age 45-55")
                rate = df.groupby("age_group")["n_events"].mean()
                rows.append(dict(temp_factor=ft, hr_factor=fh, temp_thr=t_thr, hr_thr=h_thr,
                                 events=int(df["n_events"].sum()),
                                 rate_45_55=rate["45-55"], rate_18_34=rate["18-34"],
                                 rate_ratio=rr, ci_low=lo, ci_high=hi))
                print(f"temp>{t_thr:.2f} hr>={h_thr:.1f}  events={rows[-1]['events']:6d}  RR={rr:.2f} ({lo:.2f}-{hi:.2f})")
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "threshold_sensitivity.csv"), index=False)
    return out


_DF = _START = None


def _init(df, start):
    global _DF, _START
    _DF, _START = df, start


def _drop_one(pid):
    sub = _DF[_DF["participant_id"] != pid]
    theta = model_for(sub).fit_point(_START)
    return pid, np.exp(theta[1])


def leave_one_out(workers):
    df = pd.read_csv(os.path.join(OUT, "person_nights.csv"))
    start = np.load(os.path.join(OUT, "theta_main.npy"))
    pids = sorted(df["participant_id"].unique())
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(df, start)) as ex:
        res = list(ex.map(_drop_one, pids, chunksize=8))
    out = pd.DataFrame(res, columns=["dropped_participant", "rate_ratio"])
    out.to_csv(os.path.join(OUT, "leave_one_out.csv"), index=False)
    print(f"LOO over {len(out)} participants: RR min={out.rate_ratio.min():.3f} "
          f"max={out.rate_ratio.max():.3f}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--skip-loo", action="store_true")
    args = ap.parse_args()
    threshold_sweep()
    if not args.skip_loo:
        leave_one_out(args.workers)
