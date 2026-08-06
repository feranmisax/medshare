"""
Nightly pipeline: score risk, forecast demand, then run BOTH matching directions
(surplus-driven push + request-driven pull), and notify the source pharmacies that
they have a recommendation to act on (offer).


"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
from src import db, model1_expiry, model2_forecast, model3_matching, requests_match, expiry


def notify_sources():
    """Notify each source pharmacy of new RECOMMENDED items awaiting their offer."""
    recs = db.read_sql("""
        SELECT rec_id, source_pharmacy_id, target_pharmacy_id, quantity, origin
        FROM redistribution_recommendations WHERE status = 'RECOMMENDED'
    """)
    if recs.empty:
        return
    rows = []
    for _, r in recs.iterrows():
        if r["origin"] == "REQUEST":
            msg = f"{r['target_pharmacy_id']} requested stock you hold — offer {r['quantity']} units?"
        else:
            msg = f"You can offer {r['quantity']} units to {r['target_pharmacy_id']}."
        rows.append(dict(pharmacy_id=r["source_pharmacy_id"], channel="in_app",
                         message=msg, related_rec_id=int(r["rec_id"])))
    db.write_df(pd.DataFrame(rows), "notifications")


def main():
    if not db.ping():
        print("Database not reachable."); return
    print("1/6  Sweeping expired stock -> waste registry ..."); expiry.run()
    print("2/6  Scoring expiry risk (Model 1) ...");        model1_expiry.score()
    print("3/6  Forecasting demand (Model 2) ...");          model2_forecast.run()
    print("4/6  Matching surplus -> demand (push) ...");     model3_matching.run()
    print("5/6  Fulfilling stock requests (pull) ...");      requests_match.run()
    print("6/6  Notifying source pharmacies ...");           notify_sources()
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
