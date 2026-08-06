"""
FastAPI backend. Wraps the data + models + transfer workflow as a small API.

"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd

from src import db

app = FastAPI(title="Inter-Pharmacy Redistribution API", version="1.0")


@app.get("/health")
def health():
    return {"ok": db.ping()}


@app.get("/pharmacies")
def pharmacies():
    return db.read_sql("SELECT pharmacy_id, name, pharmacy_type, area FROM pharmacies ORDER BY pharmacy_id").to_dict("records")


@app.get("/pharmacies/{pharmacy_id}/at-risk")
def at_risk(pharmacy_id: str):
    """Batches at this pharmacy currently flagged High or Critical."""
    df = db.read_sql("""
        SELECT r.batch_id, d.name AS drug, d.category, b.quantity,
               b.expiry_date, r.risk_probability, r.risk_tier
        FROM expiry_risk_scores r
        JOIN inventory_batches b ON b.batch_id = r.batch_id
        JOIN drugs d ON d.drug_id = b.drug_id
        WHERE b.pharmacy_id = :pid AND r.score_date = CURRENT_DATE
          AND r.risk_tier IN ('High','Critical')
        ORDER BY r.risk_probability DESC
    """, {"pid": pharmacy_id})
    return df.to_dict("records")


@app.get("/pharmacies/{pharmacy_id}/recommendations")
def recommendations(pharmacy_id: str):
    """Recommendations where this pharmacy is the source (something to send)."""
    df = db.read_sql("""
        SELECT rec.rec_id, rec.target_pharmacy_id, d.name AS drug, rec.quantity,
               rec.match_score, rec.suggested_price, rec.distance_km, rec.status
        FROM redistribution_recommendations rec
        JOIN drugs d ON d.drug_id = rec.drug_id
        WHERE rec.source_pharmacy_id = :pid AND rec.status = 'RECOMMENDED'
        ORDER BY rec.match_score DESC
    """, {"pid": pharmacy_id})
    return df.to_dict("records")


class Decision(BaseModel):
    rec_id: int
    agreed_price: float | None = None
    agreed_quantity: int | None = None


@app.post("/recommendations/accept")
def accept(d: Decision):
    rec = db.read_sql("SELECT * FROM redistribution_recommendations WHERE rec_id = :r", {"r": d.rec_id})
    if rec.empty:
        raise HTTPException(404, "recommendation not found")
    row = rec.iloc[0]
    db.run_sql("UPDATE redistribution_recommendations SET status='ACCEPTED' WHERE rec_id=:r", {"r": d.rec_id})
    db.run_sql("""
        INSERT INTO transfers (rec_id, status, agreed_price, agreed_quantity)
        VALUES (:r, 'ACCEPTED', :p, :q)
    """, {"r": d.rec_id,
          "p": d.agreed_price if d.agreed_price is not None else float(row["suggested_price"]),
          "q": d.agreed_quantity if d.agreed_quantity is not None else int(row["quantity"])})
    return {"rec_id": d.rec_id, "status": "ACCEPTED"}


@app.post("/recommendations/{rec_id}/decline")
def decline(rec_id: int):
    db.run_sql("UPDATE redistribution_recommendations SET status='DECLINED' WHERE rec_id=:r", {"r": rec_id})
    return {"rec_id": rec_id, "status": "DECLINED"}


@app.get("/stats")
def stats():
    return db.read_sql("""
        SELECT (SELECT COUNT(*) FROM pharmacies) AS pharmacies,
               (SELECT COUNT(*) FROM inventory_batches) AS batches,
               (SELECT COUNT(*) FROM redistribution_recommendations WHERE status='RECOMMENDED') AS open_recs,
               (SELECT COUNT(*) FROM transfers WHERE status='ACCEPTED') AS accepted_transfers
    """).iloc[0].to_dict()
