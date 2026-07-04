"""
Model 3 — redistribution matching engine (SURPLUS / push side).

For every High/Critical batch at a surplus pharmacy, shortlist nearby pharmacies that
need the drug (Model 2 forecast), score the transfer on four weighted criteria
(source urgency, target urgency, geographic feasibility, financial value), and write
matches above MATCH_THRESHOLD as recommendations with origin='SURPLUS', status 'RECOMMENDED'.

Run:  python -m src.model3_matching --run
"""
import sys, argparse, math
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pulp

import config
from src import db

W = dict(src=0.35, tgt=0.35, geo=0.20, val=0.10)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * r * math.asin(math.sqrt(a))
# NOTE: swap for a maps-API road travel time in the pilot (Chapter 3, 3.3.2).


def _urgency_from_days(days):
    return float(np.clip(1.0 - days / 90.0, 0.0, 1.0))


def _urgency_price(unit_price, days):
    disc = 0.05 + (0.40 - 0.05) * math.exp(-0.04 * max(days, 0))
    return round(float(unit_price) * (1 - disc), 2)


def clear_surplus_recommendations():
    """Remove only SURPLUS-origin open recommendations (and their notifications)."""
    db.run_sql("""DELETE FROM notifications WHERE related_rec_id IN
                  (SELECT rec_id FROM redistribution_recommendations
                   WHERE status='RECOMMENDED' AND origin='SURPLUS')""")
    db.run_sql("DELETE FROM redistribution_recommendations WHERE status='RECOMMENDED' AND origin='SURPLUS'")


def run():
    ph = db.read_sql("SELECT pharmacy_id, latitude, longitude, willing_receive, willing_release FROM pharmacies")
    risk = db.read_sql("""
        SELECT r.batch_id, r.risk_probability, r.risk_tier,
               b.pharmacy_id AS source_id, b.drug_id, b.quantity, b.unit_price, b.expiry_date
        FROM expiry_risk_scores r
        JOIN inventory_batches b ON b.batch_id = r.batch_id
        WHERE r.score_date = (SELECT MAX(score_date) FROM expiry_risk_scores) AND r.risk_tier IN ('High','Critical')
          AND b.is_expired = FALSE AND b.quantity > 0 AND b.expiry_date > CURRENT_DATE
    """)
    fc = db.read_sql("""
        SELECT pharmacy_id, drug_id, q10, q50, q90
        FROM demand_forecasts WHERE forecast_date = CURRENT_DATE AND horizon_days = 30
    """)
    if risk.empty:
        print("No High/Critical batches scored today. Run model1 --score first.")
        return
    ph = ph.set_index("pharmacy_id")
    sl_q = "q10" if config.SERVICE_LEVEL <= 0.2 else ("q50" if config.SERVICE_LEVEL <= 0.6 else "q90")
    demand = fc.set_index(["pharmacy_id", "drug_id"])[sl_q].to_dict()

    today = pd.Timestamp.today().normalize()
    recs = []
    for _, b in risk.iterrows():
        src = b["source_id"]
        if src not in ph.index:
            continue
        slat, slon = ph.loc[src, ["latitude", "longitude"]]
        days = (pd.Timestamp(b["expiry_date"]) - today).days
        src_urg = _urgency_from_days(days) * float(b["risk_probability"])
        cands = []
        for tid, row in ph.iterrows():
            if tid == src or str(row["willing_receive"]).lower() == "no":
                continue
            d = demand.get((tid, int(b["drug_id"])), 0.0)
            if d <= 0:
                continue
            dist = haversine_km(slat, slon, row["latitude"], row["longitude"])
            if dist > config.MAX_DISTANCE_KM:
                continue
            cands.append((tid, d, dist))
        if not cands:
            continue
        cands.sort(key=lambda x: x[2])
        cands = cands[:config.K_NEAREST]
        maxd = max(c[1] for c in cands) or 1.0
        for tid, d, dist in cands:
            tgt_urg = float(np.clip(d / maxd, 0, 1))
            geo = float(1.0 - dist / config.MAX_DISTANCE_KM)
            qty = int(min(b["quantity"], math.floor(d)))
            if qty <= 0:
                continue
            val = float(np.clip((b["unit_price"] * qty) / 100000.0, 0, 1))
            score = W["src"]*src_urg + W["tgt"]*tgt_urg + W["geo"]*geo + W["val"]*val
            if score < config.MATCH_THRESHOLD:
                continue
            recs.append(dict(
                batch_id=int(b["batch_id"]), source_pharmacy_id=src, target_pharmacy_id=tid,
                drug_id=int(b["drug_id"]), quantity=qty, match_score=round(score, 4),
                suggested_price=_urgency_price(b["unit_price"], days),
                distance_km=round(dist, 2), status="RECOMMENDED", origin="SURPLUS"))
    if not recs:
        print("No surplus matches cleared the threshold today.")
        return
    out = pd.DataFrame(recs).sort_values("match_score", ascending=False).drop_duplicates(subset=["batch_id"], keep="first")
    clear_surplus_recommendations()
    db.write_df(out, "redistribution_recommendations")
    print(f"Generated {len(out)} surplus-driven recommendations.")


# ---------- Optimisation benchmark (Eq 3.9): transshipment LP ----------
def transshipment_benchmark(surplus, demand, value, cost, feasible):
    prob = pulp.LpProblem("transshipment", pulp.LpMaximize)
    x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for (i, j) in feasible}
    prob += pulp.lpSum((value[(i, j)] - cost[(i, j)]) * x[(i, j)] for (i, j) in feasible)
    for i in surplus:
        prob += pulp.lpSum(x[(i, j)] for (ii, j) in feasible if ii == i) <= surplus[i]
    for j in demand:
        prob += pulp.lpSum(x[(i, j)] for (i, jj) in feasible if jj == j) <= demand[j]
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    return {k: v.value() for k, v in x.items() if v.value() and v.value() > 0}


def rematch_batch(batch_id, exclude_pharmacies):
    """Re-match a single at-risk batch to the best NEW target, excluding any
    pharmacies in exclude_pharmacies (e.g. ones that already declined).
    Returns the new target pharmacy_id, or None if no alternative qualifies.
    Used when a receiver declines an offer so the surplus is re-offered elsewhere."""
    info = db.read_sql("""
        SELECT r.batch_id, r.risk_probability, b.pharmacy_id AS source_id, b.drug_id,
               b.quantity, b.unit_price, b.expiry_date
        FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id = r.batch_id
        WHERE r.batch_id = :b AND r.score_date = (SELECT MAX(score_date) FROM expiry_risk_scores)
          AND b.is_expired = FALSE AND b.quantity > 0 AND b.expiry_date > CURRENT_DATE
    """, {"b": int(batch_id)})
    if info.empty:
        return None
    b = info.iloc[0]
    ph = db.read_sql("SELECT pharmacy_id, latitude, longitude, willing_receive FROM pharmacies").set_index("pharmacy_id")
    fc = db.read_sql("""SELECT pharmacy_id, q10, q50, q90 FROM demand_forecasts
                        WHERE forecast_date = CURRENT_DATE AND horizon_days = 30 AND drug_id = :d""",
                     {"d": int(b["drug_id"])})
    if b["source_id"] not in ph.index or fc.empty:
        return None
    slat, slon = ph.loc[b["source_id"], ["latitude", "longitude"]]
    days = (pd.Timestamp(b["expiry_date"]) - pd.Timestamp.today().normalize()).days
    src_urg = _urgency_from_days(days) * float(b["risk_probability"])
    sl_q = "q10" if config.SERVICE_LEVEL <= 0.2 else ("q50" if config.SERVICE_LEVEL <= 0.6 else "q90")
    demand = fc.set_index("pharmacy_id")[sl_q].to_dict()

    cands = []
    for tid, row in ph.iterrows():
        if tid == b["source_id"] or tid in exclude_pharmacies:
            continue
        if str(row["willing_receive"]).lower() == "no":
            continue
        d = demand.get(tid, 0.0)
        if d <= 0:
            continue
        dist = haversine_km(slat, slon, row["latitude"], row["longitude"])
        if dist > config.MAX_DISTANCE_KM:
            continue
        cands.append((tid, d, dist))
    if not cands:
        return None
    cands.sort(key=lambda x: x[2]); cands = cands[:config.K_NEAREST]
    maxd = max(c[1] for c in cands) or 1.0
    best = None
    for tid, d, dist in cands:
        tgt_urg = float(np.clip(d / maxd, 0, 1))
        geo = float(1.0 - dist / config.MAX_DISTANCE_KM)
        qty = int(min(b["quantity"], math.floor(d)))
        if qty <= 0:
            continue
        val = float(np.clip((b["unit_price"] * qty) / 100000.0, 0, 1))
        score = W["src"]*src_urg + W["tgt"]*tgt_urg + W["geo"]*geo + W["val"]*val
        if score >= config.MATCH_THRESHOLD and (best is None or score > best["score"]):
            best = dict(tid=tid, qty=qty, score=round(score, 4),
                        price=_urgency_price(b["unit_price"], days), dist=round(dist, 2))
    if not best:
        return None
    db.write_df(pd.DataFrame([dict(
        batch_id=int(batch_id), source_pharmacy_id=b["source_id"], target_pharmacy_id=best["tid"],
        drug_id=int(b["drug_id"]), quantity=best["qty"], match_score=best["score"],
        suggested_price=best["price"], distance_km=best["dist"],
        status="RECOMMENDED", origin="SURPLUS")]), "redistribution_recommendations")
    return best["tid"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.run: run()
    else: print("Use --run")