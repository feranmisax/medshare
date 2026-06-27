-- ============================================================
-- Expiry handling upgrade — ADDITIVE migration (keeps data)
-- Run once:  psql -U postgres -d pharma_redist -f db/migrate_expiry.sql
-- Safe to re-run.
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

-- Done.
