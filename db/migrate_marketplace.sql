-- ============================================================
-- Marketplace upgrade — ADDITIVE migration (keeps existing data)

-- ============================================================

-- 1. Roles for users (pharmacy operator vs management/admin)
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'pharmacy';

-- 2. Recommendation origin: SURPLUS (push) or REQUEST (pull), and link to a request
ALTER TABLE redistribution_recommendations
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'SURPLUS';
ALTER TABLE redistribution_recommendations
    ADD COLUMN IF NOT EXISTS request_id BIGINT;

-- 3. Commission / platform revenue on each transfer
ALTER TABLE transfers ADD COLUMN IF NOT EXISTS commission_rate   NUMERIC(5,4) DEFAULT 0.05;
ALTER TABLE transfers ADD COLUMN IF NOT EXISTS commission_amount NUMERIC(12,2);
ALTER TABLE transfers ADD COLUMN IF NOT EXISTS gross_value       NUMERIC(12,2);

-- 4. Stock requests (the demand-driven / pull side of the marketplace)
CREATE TABLE IF NOT EXISTS stock_requests (
    request_id      BIGSERIAL PRIMARY KEY,
    pharmacy_id     TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),  -- the requester
    drug_id         INTEGER NOT NULL REFERENCES drugs(drug_id),
    quantity_needed INTEGER NOT NULL CHECK (quantity_needed > 0),
    max_price       NUMERIC(12,2),                  -- optional ceiling per unit
    needed_by       DATE,
    status          TEXT NOT NULL DEFAULT 'OPEN',    -- OPEN -> MATCHED -> FULFILLED / CANCELLED
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON stock_requests(status);

-- 5. Link recommendations.request_id to stock_requests (add FK once table exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'rec_request_fk'
    ) THEN
        ALTER TABLE redistribution_recommendations
            ADD CONSTRAINT rec_request_fk
            FOREIGN KEY (request_id) REFERENCES stock_requests(request_id);
    END IF;
END $$;

-- Done.
