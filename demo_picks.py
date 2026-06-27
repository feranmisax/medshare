from src import db

print("=== Most active pharmacies ===")
print(db.read_sql("""
    SELECT p.pharmacy_id, p.area, p.pharmacy_type,
      (SELECT COUNT(*) FROM expiry_risk_scores r
         JOIN inventory_batches b ON b.batch_id = r.batch_id
        WHERE b.pharmacy_id = p.pharmacy_id AND r.score_date = CURRENT_DATE
          AND r.risk_tier IN ('High','Critical')) AS at_risk,
      (SELECT COUNT(*) FROM redistribution_recommendations
        WHERE source_pharmacy_id = p.pharmacy_id AND status = 'RECOMMENDED') AS to_offer,
      (SELECT COUNT(*) FROM redistribution_recommendations
        WHERE target_pharmacy_id = p.pharmacy_id AND status IN ('RECOMMENDED','OFFERED')) AS incoming
    FROM pharmacies p
    ORDER BY (
      (SELECT COUNT(*) FROM expiry_risk_scores r
         JOIN inventory_batches b ON b.batch_id = r.batch_id
        WHERE b.pharmacy_id = p.pharmacy_id AND r.score_date = CURRENT_DATE
          AND r.risk_tier IN ('High','Critical'))
      + (SELECT COUNT(*) FROM redistribution_recommendations
          WHERE source_pharmacy_id = p.pharmacy_id AND status = 'RECOMMENDED')
      + (SELECT COUNT(*) FROM redistribution_recommendations
          WHERE target_pharmacy_id = p.pharmacy_id AND status IN ('RECOMMENDED','OFFERED'))
    ) DESC
    LIMIT 12
""").to_string(index=False))

print("\n=== Ready-made sender -> receiver pairs (top surplus matches) ===")
print(db.read_sql("""
    SELECT rec.source_pharmacy_id, rec.target_pharmacy_id, d.name AS drug,
           rec.quantity, ROUND(rec.match_score::numeric, 2) AS score,
           ROUND(rec.distance_km::numeric, 1) AS km
    FROM redistribution_recommendations rec
    JOIN drugs d ON d.drug_id = rec.drug_id
    WHERE rec.status = 'RECOMMENDED' AND rec.origin = 'SURPLUS'
    ORDER BY rec.match_score DESC
    LIMIT 8
""").to_string(index=False))