"""
Framework evaluation (Objective V).

Monte Carlo simulation comparing waste WITH redistribution against two baselines:
  B0 = no redistribution (do nothing)
  B1 = realistic status quo (an assumed fraction of surplus is informally cleared)

Reports (Chapter 3, §3.5.3-3.5.4):
  * the waste-reduction rate at a survey-anchored acceptance point (with 95% CI),
  * the FULL waste-reduction CURVE across acceptance rates 20%-90%,
  * the BREAK-EVEN acceptance rate (where the system first beats B1 meaningfully),
  * a sensitivity sweep over the B1 informal-clearance fraction.

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


def simulate_once(batches, demand_lookup, recs_lookup, seed, acceptance, b1_clear):
    """One paired Monte Carlo replication using COMMON RANDOM NUMBERS: the same
    per-batch demand draw and the same acceptance draw feed B0, B1 and system."""
    rng = np.random.default_rng(seed)
    today = pd.Timestamp.today().normalize()
    waste_b0 = waste_b1 = waste_sys = 0.0
    for _, b in batches.iterrows():
        days = max((b["expiry_date"] - today).days, 0)
        daily = demand_lookup.get((b["pharmacy_id"], int(b["drug_id"])), 0.05) / 30.0
        sold = rng.poisson(max(daily, 0.001) * days)           # shared demand draw
        leftover = max(b["quantity"] - sold, 0)
        val = float(b["unit_price"])
        accept_draw = rng.random()                             # shared acceptance draw

        waste_b0 += leftover * val
        waste_b1 += max(leftover - int(leftover * b1_clear), 0) * val
        rec_qty = recs_lookup.get(int(b["batch_id"]), 0)
        rescued = rec_qty if accept_draw < acceptance else 0
        waste_sys += max(leftover - rescued, 0) * val
    return waste_b0, waste_b1, waste_sys


def _reduction(batches, demand_lookup, recs_lookup, runs, acceptance, b1_clear, base_seed):
    red_b0, red_b1 = [], []
    for r in range(runs):
        seed = base_seed + r                                    # same seed across B0/B1/sys
        w0, w1, ws = simulate_once(batches, demand_lookup, recs_lookup,
                                   seed, acceptance, b1_clear)
        if w0 > 0: red_b0.append(100 * (w0 - ws) / w0)
        if w1 > 0: red_b1.append(100 * (w1 - ws) / w1)
    return np.array(red_b0), np.array(red_b1)


def _ci(a):
    return (a.mean(), np.percentile(a, 2.5), np.percentile(a, 97.5)) if len(a) else (0, 0, 0)


def main(runs, acceptance, curve):
    batches, fc, recs = _snapshot()
    if batches.empty:
        print("No batches. Run the generator + pipeline first."); return
    demand_lookup = fc.set_index(["pharmacy_id", "drug_id"])["q50"].to_dict()
    recs_lookup = recs.set_index("batch_id")["rec_qty"].to_dict()
    base_seed = config.RANDOM_SEED

    # --- point estimate at the survey-anchored acceptance rate ---
    r0, r1 = _reduction(batches, demand_lookup, recs_lookup, runs, acceptance,
                        config.DEFAULT_B1_CLEAR, base_seed)
    m0, lo0, hi0 = _ci(r0)
    m1, lo1, hi1 = _ci(r1)
    print(f"Monte Carlo runs: {runs}  |  common random numbers  |  "
          f"acceptance (survey point): {acceptance:.0%}  |  B1 clear: {config.DEFAULT_B1_CLEAR:.0%}")
    print(f"Waste-reduction vs B0 (do nothing):       {m0:5.1f}%  (95% CI {lo0:.1f}-{hi0:.1f})")
    print(f"Waste-reduction vs B1 (realistic status): {m1:5.1f}%  (95% CI {lo1:.1f}-{hi1:.1f})")
    print(f"Recommendations evaluated: {len(recs_lookup)}")

    if not curve:
        print("\n(add --curve for the acceptance-rate sweep, break-even, and B1 sensitivity)")
        return

    # --- acceptance-rate CURVE (Chapter 3 §3.5.3): report the dependence, not a point ---
    print("\nAcceptance-rate sweep (waste-reduction vs B1):")
    break_even = None
    for acc in config.ACCEPTANCE_SWEEP:
        _, rr1 = _reduction(batches, demand_lookup, recs_lookup, runs, acc,
                            config.DEFAULT_B1_CLEAR, base_seed)
        mm, l, h = _ci(rr1)
        flag = ""
        if break_even is None and mm > 1.0:                     # first acc beating B1 by >1pp
            break_even = acc; flag = "  <- break-even (>1% gain over B1)"
        print(f"  acceptance={acc:4.0%}   reduction vs B1 = {mm:5.1f}%  (CI {l:.1f}-{h:.1f}){flag}")
    if break_even is not None:
        print(f"Break-even acceptance rate (vs B1): ~{break_even:.0%}")
    else:
        print("Break-even acceptance rate (vs B1): not reached within the swept range.")

    # --- B1 informal-clearance sensitivity (Chapter 3 §3.5.4) ---
    print("\nB1 informal-clearance sensitivity (at survey acceptance point):")
    for bc in config.B1_CLEAR_SWEEP:
        _, rr1 = _reduction(batches, demand_lookup, recs_lookup, runs, acceptance, bc, base_seed)
        mm, l, h = _ci(rr1)
        print(f"  B1 clear={bc:4.0%}   reduction vs B1 = {mm:5.1f}%  (CI {l:.1f}-{h:.1f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--acceptance", type=float, default=config.DEFAULT_ACCEPTANCE,
                    help="survey-anchored assumption: share of recommendations accepted")
    ap.add_argument("--curve", action="store_true",
                    help="report the full acceptance-rate curve, break-even, and B1 sensitivity")
    a = ap.parse_args()
    main(a.runs, a.acceptance, a.curve)
