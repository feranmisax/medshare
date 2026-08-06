-- ============================================================
-- Inter-Pharmacy Redistribution — database schema

-- ============================================================

DROP TABLE IF EXISTS notifications        CASCADE;
DROP TABLE IF EXISTS price_negotiations   CASCADE;
DROP TABLE IF EXISTS transfers            CASCADE;
DROP TABLE IF EXISTS redistribution_recommendations CASCADE;
DROP TABLE IF EXISTS demand_forecasts     CASCADE;
DROP TABLE IF EXISTS expiry_risk_scores   CASCADE;
DROP TABLE IF EXISTS sales_daily          CASCADE;
DROP TABLE IF EXISTS inventory_batches    CASCADE;
DROP TABLE IF EXISTS drugs                CASCADE;
DROP TABLE IF EXISTS users                CASCADE;
DROP TABLE IF EXISTS pharmacies           CASCADE;

-- ---------- 1. Pharmacies (nodes in the network) ----------
CREATE TABLE pharmacies (
    pharmacy_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    pharmacy_type   TEXT NOT NULL,            -- Independent / Hospital-Clinic / Small chain / Large chain
    area            TEXT,
    landmark        TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    willing_receive TEXT,                      -- Yes / Maybe / No
    willing_release TEXT,
    travel_km_max   DOUBLE PRECISION,
    is_synthetic    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------- 2. Drug catalogue ----------
CREATE TABLE drugs (
    drug_id   SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,
    pack_size INTEGER DEFAULT 1,
    unit      TEXT DEFAULT 'unit',
    UNIQUE (name, category)
);

-- ---------- 3. Inventory batches (batch-level stock) ----------
CREATE TABLE inventory_batches (
    batch_id        BIGSERIAL PRIMARY KEY,
    pharmacy_id     TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    drug_id         INTEGER NOT NULL REFERENCES drugs(drug_id),
    quantity        INTEGER NOT NULL CHECK (quantity >= 0),
    unit_cost       NUMERIC(12,2) CHECK (unit_cost >= 0),
    unit_price      NUMERIC(12,2) CHECK (unit_price >= 0),
    manufacture_date DATE,
    expiry_date     DATE NOT NULL,
    received_date   DATE NOT NULL,
    is_synthetic    BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (expiry_date > manufacture_date)
);
CREATE INDEX idx_batches_pharmacy ON inventory_batches(pharmacy_id);
CREATE INDEX idx_batches_expiry   ON inventory_batches(expiry_date);

-- ---------- 4. Daily sales (demand time series) ----------
CREATE TABLE sales_daily (
    id          BIGSERIAL PRIMARY KEY,
    pharmacy_id TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    drug_id     INTEGER NOT NULL REFERENCES drugs(drug_id),
    sale_date   DATE NOT NULL,
    units_sold  INTEGER NOT NULL CHECK (units_sold >= 0),
    UNIQUE (pharmacy_id, drug_id, sale_date)
);
CREATE INDEX idx_sales_pd ON sales_daily(pharmacy_id, drug_id);

-- ---------- 5. Expiry-risk scores (Model 1 output) ----------
CREATE TABLE expiry_risk_scores (
    id               BIGSERIAL PRIMARY KEY,
    batch_id         BIGINT NOT NULL REFERENCES inventory_batches(batch_id),
    score_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    risk_probability DOUBLE PRECISION NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    risk_tier        TEXT NOT NULL,           -- Low / Medium / High / Critical
    model_version    TEXT DEFAULT 'v1',
    UNIQUE (batch_id, score_date)
);

-- ---------- 6. Demand forecasts (Model 2 output, probabilistic) ----------
CREATE TABLE demand_forecasts (
    id            BIGSERIAL PRIMARY KEY,
    pharmacy_id   TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    drug_id       INTEGER NOT NULL REFERENCES drugs(drug_id),
    forecast_date DATE NOT NULL DEFAULT CURRENT_DATE,
    horizon_days  INTEGER NOT NULL,           -- 7 / 14 / 30
    q10           DOUBLE PRECISION,            -- low demand quantile
    q50           DOUBLE PRECISION,            -- median
    q90           DOUBLE PRECISION,            -- high demand quantile
    method        TEXT,                        -- HoltWinters / TSB / Croston / etc.
    UNIQUE (pharmacy_id, drug_id, forecast_date, horizon_days)
);

-- ---------- 7. Redistribution recommendations (Model 3 output) ----------
CREATE TABLE redistribution_recommendations (
    rec_id             BIGSERIAL PRIMARY KEY,
    batch_id           BIGINT NOT NULL REFERENCES inventory_batches(batch_id),
    source_pharmacy_id TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    target_pharmacy_id TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    drug_id            INTEGER NOT NULL REFERENCES drugs(drug_id),
    quantity           INTEGER NOT NULL CHECK (quantity > 0),
    match_score        DOUBLE PRECISION NOT NULL,
    suggested_price    NUMERIC(12,2),
    distance_km        DOUBLE PRECISION,
    status             TEXT NOT NULL DEFAULT 'RECOMMENDED',
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (source_pharmacy_id <> target_pharmacy_id)
);
CREATE INDEX idx_recs_status ON redistribution_recommendations(status);

-- ---------- Coordination: transfers (state machine) ----------
CREATE TABLE transfers (
    transfer_id     BIGSERIAL PRIMARY KEY,
    rec_id          BIGINT NOT NULL REFERENCES redistribution_recommendations(rec_id),
    status          TEXT NOT NULL DEFAULT 'OFFERED',
        -- OFFERED -> ACCEPTED -> IN_TRANSIT -> COMPLETED ; or DECLINED / EXPIRED
    agreed_price    NUMERIC(12,2),
    agreed_quantity INTEGER,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------- Coordination: price negotiations ----------
CREATE TABLE price_negotiations (
    id            BIGSERIAL PRIMARY KEY,
    rec_id        BIGINT NOT NULL REFERENCES redistribution_recommendations(rec_id),
    proposer      TEXT NOT NULL,               -- 'source' or 'target'
    proposed_price NUMERIC(12,2) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------- Coordination: notifications ----------
CREATE TABLE notifications (
    id             BIGSERIAL PRIMARY KEY,
    pharmacy_id    TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    channel        TEXT NOT NULL DEFAULT 'in_app',  -- in_app / sms / whatsapp
    message        TEXT NOT NULL,
    related_rec_id BIGINT REFERENCES redistribution_recommendations(rec_id),
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    read_at        TIMESTAMP
);

-- ---------- Auth: users (PCN number as username) ----------
CREATE TABLE users (
    user_id       BIGSERIAL PRIMARY KEY,
    pharmacy_id   TEXT NOT NULL REFERENCES pharmacies(pharmacy_id),
    pcn_number    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Done.
