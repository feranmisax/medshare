"""
Expiry sweep — move lapsed batches out of circulation into the waste registry.

A batch is 'expired' when its expiry_date is on or before today. The sweep:
  1. logs each newly-expired batch to expired_stock (units, value lost),
  2. sets is_expired = TRUE and quantity = 0 so it disappears from stock,
     at-risk views, and all matching,
  3. withdraws any open recommendations/offers for that batch (and notifies).

Called automatically by the pipeline.
"""
import sys, argparse
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src import db


def run():
    # batches that have lapsed but aren't yet logged
    lapsed = db.read_sql("""
        SELECT batch_id, pharmacy_id, drug_id, quantity, unit_cost, unit_price, expiry_date
        FROM inventory_batches
        WHERE is_expired = FALSE AND quantity > 0 AND expiry_date <= CURRENT_DATE
    """)
    if lapsed.empty:
        print("No newly-expired batches.")
        return 0

    n = 0
    for _, b in lapsed.iterrows():
        bid = int(b["batch_id"])
        value_lost = float(b["quantity"]) * float(b["unit_cost"] or 0)
        # 1. log to the waste registry (UNIQUE on batch_id makes this idempotent)
        db.run_sql("""
            INSERT INTO expired_stock
              (batch_id, pharmacy_id, drug_id, units_expired, unit_cost, unit_price, value_lost, expiry_date)
            VALUES (:b,:p,:d,:u,:uc,:up,:vl,:ed)
            ON CONFLICT (batch_id) DO NOTHING
        """, {"b": bid, "p": b["pharmacy_id"], "d": int(b["drug_id"]),
              "u": int(b["quantity"]), "uc": float(b["unit_cost"] or 0),
              "up": float(b["unit_price"] or 0), "vl": value_lost, "ed": b["expiry_date"]})
        # 2. withdraw any open recs/offers for this batch, and notify the parties
        open_recs = db.read_sql("""
            SELECT rec_id, source_pharmacy_id, target_pharmacy_id
            FROM redistribution_recommendations
            WHERE batch_id = :b AND status IN ('RECOMMENDED','OFFERED')
        """, {"b": bid})
        for _, rr in open_recs.iterrows():
            for pid in (rr["source_pharmacy_id"], rr["target_pharmacy_id"]):
                db.run_sql("""INSERT INTO notifications (pharmacy_id,channel,message,related_rec_id)
                              VALUES (:p,'in_app',:m,:r)""",
                           {"p": pid, "m": "A transfer was withdrawn because the stock expired.",
                            "r": int(rr["rec_id"])})
        db.run_sql("""DELETE FROM notifications WHERE related_rec_id IN
                      (SELECT rec_id FROM redistribution_recommendations
                       WHERE batch_id=:b AND status IN ('RECOMMENDED','OFFERED')) AND read_at IS NOT NULL""",
                   {"b": bid})
        db.run_sql("""UPDATE redistribution_recommendations SET status='EXPIRED'
                      WHERE batch_id=:b AND status IN ('RECOMMENDED','OFFERED')""", {"b": bid})
        # 3. take it out of circulation
        db.run_sql("UPDATE inventory_batches SET is_expired=TRUE, quantity=0 WHERE batch_id=:b", {"b": bid})
        # 4. drop any risk scores for this batch — once expired it is no longer a
        #    prediction. (The DB trigger also enforces this; kept here so the sweep
        #    is correct even on a database where the trigger has not been applied.)
        db.run_sql("DELETE FROM expiry_risk_scores WHERE batch_id=:b", {"b": bid})
        n += 1

    total = db.read_sql("SELECT COALESCE(SUM(value_lost),0) v FROM expired_stock").iloc[0]["v"]
    print(f"Logged {n} expired batch(es). Cumulative waste in registry: ₦{float(total):,.0f}")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.run: run()
    else: print("Use --run")