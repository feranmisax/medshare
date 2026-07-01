-- Records the unit price of each sale, so sales value can be computed exactly
-- as SUM(units_sold * unit_price). Safe to run multiple times.
ALTER TABLE sales_daily ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12,2);