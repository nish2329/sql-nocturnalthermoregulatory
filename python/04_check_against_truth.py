"""
Check detected events against what was injected into the synthetic data.

This stands in for the manual plausible / ambiguous / artifact review: each
detected event is matched to the injected signal it overlaps (a true
thermoregulatory event takes priority). With real data there is no truth
table and this step would be the visual review.

* plausible : overlaps an injected thermoregulatory event
* confounder: overlaps a warm arousal or falls on an alcohol night
* artifact  : overlaps a temperature-only or heart-rate-only bump
* noise     : overlaps nothing that was injected

Also reports recall: the share of injected events (on valid nights) the
detector found. Writes results/truth_check.json.
"""
import json
import os

import pandas as pd

from db import connect

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")

MATCH = """
WITH m AS (
  SELECT e.sleep_period_id, e.event_id,
         (SELECT t.kind FROM sim_truth t
           WHERE t.sleep_period_id = e.sleep_period_id
             AND t.start_ts <= e.end_ts
             AND t.end_ts   >= e.start_ts - INTERVAL '10 minutes'   -- trailing window lag
           ORDER BY (t.kind = 'thermo_event') DESC,
                    (t.kind = 'warm_arousal') DESC
           LIMIT 1) AS kind
  FROM events e
)
SELECT p.age_group, COALESCE(m.kind, 'none') AS kind, COUNT(*) AS n
FROM m JOIN valid_nights v USING (sleep_period_id)
JOIN participants p USING (participant_id)
GROUP BY 1, 2
"""

RECALL = """
SELECT p.age_group,
       COUNT(*) AS injected,
       COUNT(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM events e
           WHERE e.sleep_period_id = t.sleep_period_id
             AND t.start_ts <= e.end_ts
             AND t.end_ts   >= e.start_ts - INTERVAL '10 minutes')) AS detected
FROM sim_truth t
JOIN valid_nights v USING (sleep_period_id)
JOIN participants p ON p.participant_id = t.participant_id
WHERE t.kind = 'thermo_event'
GROUP BY 1
"""

# Injected events per night on valid nights: what a perfect detector would see.
INJECTED_RATE = """
SELECT p.age_group,
       COUNT(DISTINCT v.sleep_period_id) AS nights,
       COUNT(t.*) FILTER (WHERE t.kind = 'thermo_event') AS injected
FROM valid_nights v
JOIN participants p USING (participant_id)
LEFT JOIN sim_truth t ON t.sleep_period_id = v.sleep_period_id
GROUP BY 1
"""

LABEL = {"thermo_event": "plausible", "warm_arousal": "confounder", "alcohol_night": "confounder",
         "temp_only": "artifact", "hr_only": "artifact", "none": "noise"}


def main():
    with connect() as conn:
        m = pd.read_sql(MATCH, conn)
        r = pd.read_sql(RECALL, conn)
        inj_rate = pd.read_sql(INJECTED_RATE, conn).set_index("age_group")
    m["label"] = m["kind"].map(LABEL)

    out = {"by_kind": m.groupby("kind")["n"].sum().to_dict(),
           "by_label": {}, "recall": {}}
    for scope, sub in [("all", m)] + list(m.groupby("age_group")):
        tot = sub["n"].sum()
        out["by_label"][scope] = {k: dict(n=int(v), share=v / tot)
                                  for k, v in sub.groupby("label")["n"].sum().items()}
    for _, row in r.iterrows():
        out["recall"][row["age_group"]] = dict(injected=int(row["injected"]), detected=int(row["detected"]),
                                               recall=row["detected"] / row["injected"])
    inj, det = r["injected"].sum(), r["detected"].sum()
    out["recall"]["all"] = dict(injected=int(inj), detected=int(det), recall=det / inj)

    rate = inj_rate["injected"] / inj_rate["nights"]
    out["injected_events_per_night"] = rate.to_dict()
    out["injected_rate_ratio"] = rate["45-55"] / rate["18-34"]
    plaus = m[m["label"] == "plausible"].groupby("age_group")["n"].sum() / inj_rate["nights"]
    out["plausible_only_rate_ratio"] = plaus["45-55"] / plaus["18-34"]

    with open(os.path.join(OUT, "truth_check.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
