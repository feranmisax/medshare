-- Records the price and exact value of each sale, so sales value is a true
-- sum of recorded amounts rather than an estimate. Safe to run multiple times.
ALTER TABLE sales_daily ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12,2);

-- sale_value is always units_sold * unit_price, maintained by the database.
ALTER TABLE sales_daily ADD COLUMN IF NOT EXISTS sale_value NUMERIC(14,2)
    GENERATED ALWAYS AS (units_sold * unit_price) STORED;