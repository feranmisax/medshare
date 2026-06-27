"""
Model 3 (REQUEST / pull side) — fulfil demand-driven stock requests.

For an OPEN stock_request, search nearby pharmacies holding at-risk (High/Critical)
stock of the requested drug, score each candidate fulfiller on the same four weighted
criteria, and auto-suggest the best one as a recommendation (origin='REQUEST',
status 'RECOMMENDED', source = holder, target = requester). The holder then confirms
(offers) it in the app, completing the auto-suggest -> confirm flow.

  run()              -> match ALL open requests (used by the pipeline)
  match_one(req_id)  -> match a SINGLE request instantly (used by the app on posting)

Run:  python -m src.requests_match --run
"""
import sys, argparse
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import config
from src import db
from src.model3_matching import haversine_km, _urgency_from_days, _urgency_price, W


def clear_request_recommendations():
    """Remove REQUEST-origin open recs + their notifications, and reopen their requests."""
    db.run_sql("""DELETE FROM notifications WHERE related_rec_id IN
                  (SELECT rec_id FROM redistribution_recommendations
                   WHERE status='RECOMMENDED' AND origin='REQUEST')""")
    db.run_sql("""UPDATE stock_requests SET status='OPEN'
                  WHERE status='MATCHED' AND request_id IN
                  (SELECT request_id FROM redistribution_recommendations
                   WHERE status='RECOMMENDED' AND origin='REQUEST')""")
    db.run_sql("DELETE FROM redistribution_recommendations WHERE status='RECOMMENDED' AND origin='REQUEST'")


def _best_fulfiller(q, ph, risk, today):
    """Return the best candidate recommendation dict for one request row, or None."""
    requester = q["requester"]
    if requester not in ph.index:
        return None
    rlat, rlon = ph.loc[requester, ["latitude", "longitude"]]
    need = int(q["quantity_needed"])
    pool = risk[risk["drug_id"] == int(q["drug_id"])]
    best = None
    for _, b in pool.iterrows():
        holder = b["holder"]
        if holder == requester or holder not in ph.index:
            continue
        if str(ph.loc[holder, "willing_release"]).lower() == "no":
            continue
        hlat, hlon = ph.loc[holder, ["latitude", "longitude"]]
        dist = haversine_km(hlat, hlon, rlat, rlon)
        if dist > config.MAX_DISTANCE_KM:
            continue
        days = (pd.Timestamp(b["expiry_date"]) - today).days
        qty = int(min(int(b["quantity"]), need))
        if qty <= 0:
            continue
        price = _urgency_price(b["unit_price"], days)
        if pd.notna(q["max_price"]) and price > float(q["max_price"]):
            continue
        src_urg = _urgency_from_days(days) * float(b["risk_probability"])
        tgt_urg = float(np.clip(qty / need, 0, 1))
        geo = float(1.0 - dist / config.MAX_DISTANCE_KM)
        val = float(np.clip((b["unit_price"] * qty) / 100000.0, 0, 1))
        score = W["src"]*src_urg + W["tgt"]*tgt_urg + W["geo"]*geo + W["val"]*val
        if score >= config.MATCH_THRESHOLD and (best is None or score > best["match_score"]):
            best = dict(batch_id=int(b["batch_id"]), source_pharmacy_id=holder,
                        target_pharmacy_id=requester, drug_id=int(q["drug_id"]),
                        quantity=qty, match_score=round(score, 4), suggested_price=price,
                        distance_km=round(dist, 2), status="RECOMMENDED",
                        origin="REQUEST", request_id=int(q["request_id"]))
    return best


def _load_pharmacies():
    return db.read_sql("SELECT pharmacy_id, latitude, longitude, willing_release FROM pharmacies").set_index("pharmacy_id")


def _load_atrisk():
    return db.read_sql("""
        SELECT r.batch_id, r.risk_probability, b.pharmacy_id AS holder, b.drug_id,
               b.quantity, b.unit_price, b.expiry_date
        FROM expiry_risk_scores r
        JOIN inventory_batches b ON b.batch_id = r.batch_id
        WHERE r.score_date = CURRENT_DATE AND r.risk_tier IN ('High','Critical')
          AND b.is_expired = FALSE AND b.quantity > 0 AND b.expiry_date > CURRENT_DATE
    """)


def match_one(request_id: int) -> bool:
    """Instantly match a single OPEN request. Returns True if a fulfiller was found.
    Called by the app right after a pharmacy posts a request."""
    req = db.read_sql("""
        SELECT request_id, pharmacy_id AS requester, drug_id, quantity_needed, max_price
        FROM stock_requests WHERE request_id = :r AND status = 'OPEN'
    """, {"r": int(request_id)})
    if req.empty:
        return False
    ph, risk = _load_pharmacies(), _load_atrisk()
    if risk.empty:
        return False
    best = _best_fulfiller(req.iloc[0], ph, risk, pd.Timestamp.today().normalize())
    if not best:
        return False
    db.write_df(pd.DataFrame([best]), "redistribution_recommendations")
    db.run_sql("UPDATE stock_requests SET status='MATCHED' WHERE request_id=:r", {"r": int(request_id)})
    # notify the holder that a request awaits their offer
    db.run_sql("""INSERT INTO notifications (pharmacy_id,channel,message,related_rec_id)
                  SELECT :h,'in_app',:m, rec_id FROM redistribution_recommendations
                  WHERE request_id=:r AND status='RECOMMENDED' ORDER BY rec_id DESC LIMIT 1""",
               {"h": best["source_pharmacy_id"],
                "m": f"{best['target_pharmacy_id']} requested stock you hold — offer {best['quantity']} units?",
                "r": int(request_id)})
    return True


def run():
    reqs = db.read_sql("""
        SELECT request_id, pharmacy_id AS requester, drug_id, quantity_needed, max_price
        FROM stock_requests WHERE status = 'OPEN'
    """)
    if reqs.empty:
        print("No open stock requests to match.")
        return
    ph, risk = _load_pharmacies(), _load_atrisk()
    if risk.empty:
        print("No at-risk stock available to fulfil requests today.")
        return
    clear_request_recommendations()
    today = pd.Timestamp.today().normalize()
    recs, matched = [], []
    for _, q in reqs.iterrows():
        best = _best_fulfiller(q, ph, risk, today)
        if best:
            recs.append(best)
            matched.append(int(q["request_id"]))
    if not recs:
        print("No fulfiller cleared the threshold for the open requests.")
        return
    db.write_df(pd.DataFrame(recs), "redistribution_recommendations")
    for rid in matched:
        db.run_sql("UPDATE stock_requests SET status='MATCHED' WHERE request_id=:r", {"r": rid})
    print(f"Auto-suggested fulfillers for {len(recs)} request(s).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.run: run()
    else: print("Use --run")
