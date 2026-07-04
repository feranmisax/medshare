"""Lists pharmacies holding High/Critical (at-risk) batches, ranked by at-risk value."""
from src import db

df = db.read_sql("""
    WITH latest AS (
        SELECT MAX(score_date) AS d FROM expiry_risk_scores
    )
    SELECT
        p.pharmacy_id,
        p.area,
        p.pharmacy_type,
        COUNT(*)                                    AS at_risk_batches,
        SUM(CASE WHEN s.risk_tier='Critical' THEN 1 ELSE 0 END) AS critical_batches,
        ROUND(SUM(b.quantity * b.unit_price)::numeric, 0)       AS at_risk_value
    FROM expiry_risk_scores s
    JOIN latest       ON s.score_date = latest.d
    JOIN inventory_batches b ON b.batch_id = s.batch_id
    JOIN pharmacies   p ON p.pharmacy_id = b.pharmacy_id
    WHERE s.risk_tier IN ('High','Critical')
    GROUP BY p.pharmacy_id, p.area, p.pharmacy_type
    ORDER BY at_risk_value DESC
""")

if df.empty:
    print("No pharmacies currently hold High/Critical (at-risk) batches.")
else:
    print(f"=== Pharmacies with at-risk (High/Critical) drugs — {len(df)} pharmacies ===")
    print(df.to_string(index=False))
    print(f"\nTotal at-risk value across network: NGN {df['at_risk_value'].sum():,.0f}")