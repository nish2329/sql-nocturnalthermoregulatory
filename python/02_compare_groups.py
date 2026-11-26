"""
Group comparison.

* Events per night by age group, with participant-level bootstrap CIs.
* Negative binomial mixed model (random intercept per participant, log hours
  slept as offset, bedtime and season as covariates).
* Cross-check: NB GEE with exchangeable correlation (population-averaged).
* Event characteristics: duration, peak temperature z, peak heart-rate rise.

Writes results/summary.json, results/model_summary.txt and results/person_nights.csv.
"""
import json
import os

import numpy as np
import pandas as pd
import statsmodels.api as sm

from db import connect
from nbglmm import design, model_for

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
os.makedirs(OUT, exist_ok=True)


def bootstrap_rate(df, n_boot=2000, seed=1):
    """Events per night, resampling participants (not nights)."""
    rng = np.random.default_rng(seed)
    per = df.groupby("participant_id").agg(ev=("n_events", "sum"), nights=("n_events", "size"))
    ev, nights = per["ev"].values, per["nights"].values
    idx = rng.integers(0, len(per), (n_boot, len(per)))
    boots = ev[idx].sum(1) / nights[idx].sum(1)
    return ev.sum() / nights.sum(), np.percentile(boots, 2.5), np.percentile(boots, 97.5)


def main():
    with connect() as conn:
        df = pd.read_sql("SELECT * FROM person_night_summary", conn)
        events = pd.read_sql("SELECT * FROM events", conn)
        counts = pd.read_sql("""
            SELECT (SELECT COUNT(*) FROM participants)  AS participants_raw,
                   (SELECT COUNT(*) FROM sleep_periods) AS nights_raw,
                   (SELECT COUNT(*) FROM raw_readings)  AS readings_raw,
                   (SELECT COUNT(*) FROM clean_readings) AS readings_clean,
                   (SELECT COUNT(*) FROM valid_nights)  AS nights_valid
        """, conn).iloc[0].to_dict()
    df.to_csv(os.path.join(OUT, "person_nights.csv"), index=False)

    groups = {}
    for g, sub in df.groupby("age_group"):
        rate, lo, hi = bootstrap_rate(sub)
        groups[g] = dict(participants=int(sub["participant_id"].nunique()), nights=int(len(sub)),
                         events=int(sub["n_events"].sum()), events_per_night=rate,
                         ci_low=lo, ci_high=hi,
                         pct_nights_with_event=float((sub["n_events"] > 0).mean()))

    fit, theta = model_for(df).fit()
    rr, rr_lo, rr_hi = fit.rate_ratio("age 45-55")
    np.save(os.path.join(OUT, "theta_main.npy"), theta)

    # Cross-check with a population-averaged NB GEE
    X, names = design(df)
    gee = sm.GEE(df["n_events"], X, groups=df["participant_id"], offset=np.log(df["hours_slept"]),
                 family=sm.families.NegativeBinomial(alpha=fit.alpha),
                 cov_struct=sm.cov_struct.Exchangeable()).fit()
    b, s = gee.params.iloc[1], gee.bse.iloc[1]
    gee_rr = (np.exp(b), np.exp(b - 1.96 * s), np.exp(b + 1.96 * s))

    # Crude rate ratio without covariates, for reference
    crude = groups["45-55"]["events_per_night"] / groups["18-34"]["events_per_night"]

    ev = events.merge(df[["sleep_period_id", "age_group"]], on="sleep_period_id")
    char = {g: dict(duration_min_median=float(s["duration_min"].median()),
                    duration_min_iqr=[float(s["duration_min"].quantile(.25)), float(s["duration_min"].quantile(.75))],
                    peak_temp_z_median=float(s["peak_temp_z"].median()),
                    peak_hr_delta_median=float(s["peak_hr_delta"].median()))
            for g, s in [("all", ev)] + list(ev.groupby("age_group"))}

    summary = dict(counts={k: int(v) for k, v in counts.items()},
                   participants=int(df["participant_id"].nunique()),
                   nights=int(len(df)), events=int(df["n_events"].sum()),
                   groups=groups,
                   crude_rate_ratio=crude,
                   model=dict(rate_ratio=rr, ci_low=rr_lo, ci_high=rr_hi,
                              alpha=fit.alpha, sigma=fit.sigma, converged=fit.converged),
                   gee=dict(rate_ratio=gee_rr[0], ci_low=gee_rr[1], ci_high=gee_rr[2]),
                   event_characteristics=char)

    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=float)
    with open(os.path.join(OUT, "model_summary.txt"), "w") as f:
        f.write("Negative binomial mixed model, random intercept per participant\n")
        f.write("offset = log(hours slept); reference = age 18-34, winter\n\n")
        f.write(fit.summary() + "\n\n")
        f.write("NB GEE (exchangeable) cross-check, age 45-55 rate ratio: "
                f"{gee_rr[0]:.2f} ({gee_rr[1]:.2f} to {gee_rr[2]:.2f})\n")

    print(fit.summary())
    print(json.dumps(summary, indent=2, default=float))


if __name__ == "__main__":
    main()
