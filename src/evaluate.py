"""
Framework evaluation (Objective V).

Monte Carlo simulation comparing waste WITH redistribution against two baselines:
  B0 = no redistribution (do nothing)
  B1 = realistic status quo (a fraction of surplus is informally cleared)
Reports the waste-reduction rate (Eq 3.11) with 95% confidence intervals.

This is a self-contained simulation over the current batches + forecasts; it does
not modify the database.

Run:  python -m src.evaluate --runs 200
"""
import sys, argparse
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import config
from src import db


def _snapshot():
    batches = db.read_sql("""
        SELECT b.batch_id, b.pharmacy_id, b.drug_id, b.quantity, b.unit_price,
               b.expiry_date FROM inventory_batches b
    """)
    batches["expiry_date"] = pd.to_datetime(batches["expiry_date"])
    fc = db.read_sql("""
        SELECT pharmacy_id, drug_id, q50 FROM demand_forecasts
        WHERE forecast_date = CURRENT_DATE AND horizon_days = 30
    """)
    recs = db.read_sql("""
        SELECT batch_id, quantity AS rec_qty FROM redistribution_recommendations
        WHERE status = 'RECOMMENDED'
    """)
    return batches, fc, recs


def simulate_once(batches, demand_lookup, recs_lookup, rng, acceptance, b1_clear=0.15):
    today = pd.Timestamp.today().normalize()
    waste_b0 = waste_b1 = waste_sys = 0.0
    for _, b in batches.iterrows():
        days = max((b["expiry_date"] - today).days, 0)
        daily = demand_lookup.get((b["pharmacy_id"], int(b["drug_id"])), 0.05) / 30.0
        # stochastic demand over remaining shelf life
        sold = rng.poisson(max(daily, 0.001) * days)
        leftover = max(b["quantity"] - sold, 0)
        val = float(b["unit_price"])
        waste_b0 += leftover * val
        waste_b1 += max(leftover - int(leftover * b1_clear), 0) * val
        # system: if this batch had a recommendation and it's accepted, that qty is rescued
        rec_qty = recs_lookup.get(int(b["batch_id"]), 0)
        rescued = rec_qty if rng.random() < acceptance else 0
        waste_sys += max(leftover - rescued, 0) * val
    return waste_b0, waste_b1, waste_sys


def main(runs, acceptance):
    batches, fc, recs = _snapshot()
    if batches.empty:
        print("No batches. Run the generator + pipeline first."); return
    demand_lookup = fc.set_index(["pharmacy_id","drug_id"])["q50"].to_dict()
    recs_lookup = recs.set_index("batch_id")["rec_qty"].to_dict()
    rng = np.random.default_rng(config.RANDOM_SEED)

    red_vs_b0, red_vs_b1 = [], []
    for _ in range(runs):
        w0, w1, ws = simulate_once(batches, demand_lookup, recs_lookup, rng, acceptance)
        if w0 > 0: red_vs_b0.append(100 * (w0 - ws) / w0)
        if w1 > 0: red_vs_b1.append(100 * (w1 - ws) / w1)

    def ci(a):
        a = np.array(a)
        return a.mean(), np.percentile(a, 2.5), np.percentile(a, 97.5)

    m0, lo0, hi0 = ci(red_vs_b0)
    m1, lo1, hi1 = ci(red_vs_b1)
    print(f"Monte Carlo runs: {runs}   |   assumed acceptance rate: {acceptance:.0%}")
    print(f"Waste-reduction vs B0 (do nothing):       {m0:5.1f}%  (95% CI {lo0:.1f}–{hi0:.1f})")
    print(f"Waste-reduction vs B1 (realistic status): {m1:5.1f}%  (95% CI {lo1:.1f}–{hi1:.1f})")
    print(f"Recommendations evaluated: {len(recs_lookup)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--acceptance", type=float, default=0.64,
                    help="survey-anchored assumption: share of recommendations accepted")
    a = ap.parse_args()
    main(a.runs, a.acceptance)
