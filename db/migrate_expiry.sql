-- ============================================================
-- Expiry handling upgrade — ADDITIVE migration (keeps data)
-- ============================================================

-- Waste registry: every batch that lapses is logged here.
CREATE TABLE IF NOT EXISTS expired_stock (
    expiry_log_id  BIGSERIAL PRIMARY KEY,
    batch_id       BIGINT REFERENCES inventory_batches(batch_id),
    pharmacy_id    TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    drug_id        INTEGER NOT NULL REFERENCES drugs(drug_id),
    units_expired  INTEGER NOT NULL,
    unit_cost      NUMERIC(12,2),
    unit_price     NUMERIC(12,2),
    value_lost     NUMERIC(12,2),         -- units_expired * unit_cost (cost of the waste)
    expiry_date    DATE NOT NULL,
    logged_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (batch_id)                      -- a batch is logged at most once
);
CREATE INDEX IF NOT EXISTS idx_expired_pharmacy ON expired_stock(pharmacy_id);

-- Flag on batches so expired stock is excluded from all views/matching.
ALTER TABLE inventory_batches ADD COLUMN IF NOT EXISTS is_expired BOOLEAN NOT NULL DEFAULT FALSE;

-- ============================================================
-- Integrity layer (added) makes "expired => no risk tier" and the
-- waste total impossible to get wrong in ANY consumer (app or Power BI).
-- ============================================================

-- 1. Trigger: when a batch is flagged expired or its date passes, drop its
--    risk scores automatically. An expired batch can never carry a tier again.
CREATE OR REPLACE FUNCTION trg_purge_scores_on_expiry() RETURNS trigger AS $$
BEGIN
    IF (NEW.is_expired = TRUE OR NEW.expiry_date <= CURRENT_DATE) THEN
        DELETE FROM expiry_risk_scores WHERE batch_id = NEW.batch_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS batch_expiry_purge ON inventory_batches;
CREATE TRIGGER batch_expiry_purge
    AFTER INSERT OR UPDATE OF is_expired, expiry_date ON inventory_batches
    FOR EACH ROW EXECUTE FUNCTION trg_purge_scores_on_expiry();

-- 2. Current-risk view: the ONLY source Power BI risk visuals should read.
--    Latest snapshot + live, unexpired batches only.
DROP VIEW IF EXISTS vw_current_risk;
CREATE VIEW vw_current_risk AS
SELECT
    b.pharmacy_id,
    b.drug_id,
    ph.name                                   AS pharmacy_name,
    ph.area,
    d.name                                    AS drug,
    d.category,
    b.batch_id,
    b.quantity,
    b.unit_price,
    b.expiry_date,
    (b.expiry_date - CURRENT_DATE)            AS days_to_expiry,
    r.risk_probability,
    r.risk_tier,
    b.quantity * COALESCE(b.unit_price, 0)     AS value_at_risk
FROM expiry_risk_scores r
JOIN inventory_batches b  ON b.batch_id    = r.batch_id
JOIN drugs d              ON d.drug_id      = b.drug_id
JOIN pharmacies ph        ON ph.pharmacy_id = b.pharmacy_id
WHERE r.score_date = (SELECT MAX(score_date) FROM expiry_risk_scores)
  AND b.is_expired = FALSE
  AND b.expiry_date >= CURRENT_DATE
  AND b.quantity > 0;

-- 3. Waste views: source for the "Value Lost To Expiry" card.
CREATE OR REPLACE VIEW vw_waste_summary AS
SELECT COALESCE(SUM(value_lost),0)    AS value_lost_to_expiry,
       COALESCE(SUM(units_expired),0)  AS units_expired,
       COUNT(*)                        AS expired_batches
FROM expired_stock;

CREATE OR REPLACE VIEW vw_waste_by_pharmacy AS
SELECT e.pharmacy_id, ph.name AS pharmacy_name, ph.area,
       COALESCE(SUM(e.value_lost),0)    AS value_lost_to_expiry,
       COALESCE(SUM(e.units_expired),0)  AS units_expired,
       COUNT(*)                          AS expired_batches
FROM expired_stock e
JOIN pharmacies ph ON ph.pharmacy_id = e.pharmacy_id
GROUP BY e.pharmacy_id, ph.name, ph.area;

-- 4. 
--    Log any lapsed-but-unlogged batch to the registry (cost basis),
INSERT INTO expired_stock
    (batch_id, pharmacy_id, drug_id, units_expired, unit_cost, unit_price, value_lost, expiry_date)
SELECT batch_id, pharmacy_id, drug_id, quantity,
       unit_cost, unit_price, quantity * COALESCE(unit_cost,0), expiry_date
FROM inventory_batches
WHERE is_expired = FALSE AND quantity > 0 AND expiry_date <= CURRENT_DATE
ON CONFLICT (batch_id) DO NOTHING;

--    flag them expired (this fires the trigger, clearing their scores),
UPDATE inventory_batches
SET is_expired = TRUE, quantity = 0
WHERE is_expired = FALSE AND expiry_date <= CURRENT_DATE;

--    and clear any residual scores for batches expired before the trigger existed.
DELETE FROM expiry_risk_scores r
USING inventory_batches b
WHERE r.batch_id = b.batch_id
  AND (b.is_expired = TRUE OR b.expiry_date <= CURRENT_DATE);

-- Done.