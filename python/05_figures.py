"""
Figures.

  fig1_example_night.png        one night with a flagged event, signal vs personal baseline
  fig2_rate_by_group.png        events per night by age group (per-person rates + group mean/CI)
  fig3_threshold_sensitivity.png  age-group rate ratio across +/-20% thresholds
  fig4_leave_one_out.png        rate ratio when each participant is dropped
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from db import connect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RES, FIG = os.path.join(ROOT, "results"), os.path.join(ROOT, "figures")
os.makedirs(FIG, exist_ok=True)

INK, INK2, GRID = "#191919", "#666666", "#e6e6e6"
BLUE, ORANGE, AQUA = "#257de0", "#f47230", "#00b894"
GROUP_COLOR = {"18-34": BLUE, "45-55": ORANGE}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlelocation": "left",
    "savefig.dpi": 200, "savefig.bbox": "tight", "lines.linewidth": 2,
})


def fig1(conn):
    pick = pd.read_sql("""
        SELECT e.sleep_period_id, e.start_ts, e.end_ts
        FROM events e
        JOIN participants p USING (participant_id)
        JOIN valid_nights v USING (sleep_period_id)
        WHERE p.age_group = '45-55' AND v.n_gaps = 0
          AND e.sleep_period_id IN (SELECT sleep_period_id FROM events GROUP BY 1 HAVING COUNT(*) = 1)
          AND e.peak_temp_z BETWEEN 4 AND 7 AND e.duration_min BETWEEN 12 AND 25
        ORDER BY e.sleep_period_id LIMIT 1
    """, conn).iloc[0]
    night = pd.read_sql("""
        SELECT ts, skin_temp, heart_rate, temp_med, hr_med
        FROM scored_readings WHERE sleep_period_id = %s ORDER BY ts
    """, conn, params=(pick.sleep_period_id,))
    # break the line where minutes are missing instead of drawing across the gap
    night = night.set_index("ts").resample("1min").asfreq().reset_index()
    t0 = night.ts.iloc[0]
    hrs = (night.ts - t0).dt.total_seconds() / 3600
    ev0 = (pick.start_ts - t0).total_seconds() / 3600 - 9 / 60   # trailing window start
    ev1 = (pick.end_ts - t0).total_seconds() / 3600

    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 5), sharex=True, gridspec_kw=dict(hspace=0.25))
    for ax, col, base, c, lab in [(a, "skin_temp", "temp_med", ORANGE, "Skin temperature (°C)"),
                                 (b, "heart_rate", "hr_med", BLUE, "Heart rate (bpm)")]:
        ax.axvspan(ev0, ev1, color="#f2a600", alpha=0.18, lw=0)
        ax.plot(hrs, night[base].ffill(), color=INK2, lw=1.5, ls="--", drawstyle="steps-post")
        ax.plot(hrs, night[col], color=c, lw=1.2)
        ax.set_ylabel(lab)
        ax.text(hrs.iloc[-1], night[base].ffill().iloc[-1], "  personal\n  baseline", color=INK2,
                va="center", fontsize=8)
    a.text(ev1 + 0.05, a.get_ylim()[1], "flagged event", color=INK, va="top", fontsize=9)
    a.set_title(f"Figure 1. Example night with one flagged event (participant aged 45-55)")
    b.set_xlabel(f"Hours since sleep onset ({t0:%H:%M})")
    fig.savefig(os.path.join(FIG, "fig1_example_night.png"))
    plt.close(fig)


def fig2(summary):
    df = pd.read_csv(os.path.join(RES, "person_nights.csv"))
    per = df.groupby(["participant_id", "age_group"]).n_events.mean().reset_index()
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for i, g in enumerate(["18-34", "45-55"]):
        sub = per[per.age_group == g]
        ax.scatter(i + rng.uniform(-0.18, 0.18, len(sub)), sub.n_events, s=10,
                   color=GROUP_COLOR[g], alpha=0.35, lw=0)
        s = summary["groups"][g]
        ax.errorbar(i + 0.32, s["events_per_night"],
                    yerr=[[s["events_per_night"] - s["ci_low"]], [s["ci_high"] - s["events_per_night"]]],
                    fmt="o", ms=8, color=INK, capsize=4, lw=1.5)
        ax.text(i + 0.40, s["events_per_night"], f"{s['events_per_night']:.2f}", va="center", fontsize=9)
    ax.set_xticks([0, 1], [f"18 to 34\n(n = {summary['groups']['18-34']['participants']})",
                           f"45 to 55\n(n = {summary['groups']['45-55']['participants']})"])
    ax.set_xlim(-0.5, 1.75)
    ax.set_ylabel("Candidate events per night")
    ax.grid(axis="x", visible=False)
    m = summary["model"]
    ax.set_title("Figure 2. Event rate by age group")
    ax.text(0, -0.22, f"Dots: one participant's mean. Black: group mean with 95% bootstrap CI.\n"
                      f"Adjusted rate ratio {m['rate_ratio']:.2f} (95% CI {m['ci_low']:.2f} to {m['ci_high']:.2f}).",
            transform=ax.transAxes, fontsize=8, color=INK2, va="top")
    fig.savefig(os.path.join(FIG, "fig2_rate_by_group.png"))
    plt.close(fig)


def fig3():
    ts = pd.read_csv(os.path.join(RES, "threshold_sensitivity.csv"))
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for fh, c in [(0.8, AQUA), (1.0, INK), (1.2, BLUE)]:
        sub = ts[np.isclose(ts.hr_factor, fh)].sort_values("temp_factor")
        x = (sub.temp_factor - 1) * 100
        if fh == 1.0:
            ax.fill_between(x, sub.ci_low, sub.ci_high, color=INK, alpha=0.08, lw=0)
        ax.plot(x, sub.rate_ratio, color=c, marker="o", ms=5,
                label=f"HR rise ≥ {8 * fh:.1f} bpm" + (" (default)" if fh == 1.0 else ""))
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK)
    ax.axhline(1, color=INK2, lw=1)
    ax.set_xticks([-20, -10, 0, 10, 20], ["-20%\n(z > 1.6)", "-10%", "0\n(z > 2.0)", "+10%", "+20%\n(z > 2.4)"])
    ax.set_xlim(-23, 23)
    ax.set_ylim(0, max(3.5, ts.ci_high.max() * 1.05))
    ax.set_xlabel("Change in temperature threshold")
    ax.set_ylabel("Rate ratio, 45-55 vs 18-34")
    ax.set_title("Figure 3. Threshold sensitivity")
    ax.text(0, -0.25, f"Across all 25 combinations: rate ratio {ts.rate_ratio.min():.2f} to {ts.rate_ratio.max():.2f}. "
                      "Shaded band: 95% CI at the default heart-rate threshold.",
            transform=ax.transAxes, fontsize=8, color=INK2, va="top")
    fig.savefig(os.path.join(FIG, "fig3_threshold_sensitivity.png"))
    plt.close(fig)


def fig4(summary):
    path = os.path.join(RES, "leave_one_out.csv")
    if not os.path.exists(path):
        return
    loo = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.hist(loo.rate_ratio, bins=40, color=BLUE, edgecolor="white", linewidth=0.5)
    ax.axvline(summary["model"]["rate_ratio"], color=INK, lw=1.5, ls="--")
    ax.text(summary["model"]["rate_ratio"], ax.get_ylim()[1], "  full sample", va="top", fontsize=8)
    ax.set_xlabel("Rate ratio with one participant dropped")
    ax.set_ylabel("Refits")
    ax.grid(axis="x", visible=False)
    ax.set_title(f"Figure 4. Leave-one-participant-out ({len(loo)} refits)")
    fig.savefig(os.path.join(FIG, "fig4_leave_one_out.png"))
    plt.close(fig)


if __name__ == "__main__":
    with open(os.path.join(RES, "summary.json")) as f:
        summary = json.load(f)
    with connect() as conn:
        fig1(conn)
    fig2(summary)
    if os.path.exists(os.path.join(RES, "threshold_sensitivity.csv")):
        fig3()
    fig4(summary)
    print("figures written to", os.path.abspath(FIG))
