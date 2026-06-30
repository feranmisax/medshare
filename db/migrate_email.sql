-- Adds an email address to each pharmacy, for report delivery.
-- Safe to run multiple times.
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS email TEXT;
