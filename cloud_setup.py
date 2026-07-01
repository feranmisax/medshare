"""
One-shot cloud database initialiser.

Point DATABASE_URL at your cloud Postgres (in .env or as a shell variable),
then run:  python cloud_setup.py

It applies schema.sql + both migrations, generates the data, seeds logins,
and runs the pipeline — leaving the cloud database fully populated.
"""
import sys, subprocess
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

from sqlalchemy import text
from src import db
import config

ROOT = Path(__file__).resolve().parent
SQL_FILES = ["db/schema.sql", "db/migrate_marketplace.sql", "db/migrate_expiry.sql", "db/migrate_email.sql", "db/migrate_sales_price.sql"]


def run_sql_file(path):
    sql = (ROOT / path).read_text(encoding="utf-8")
    with db.engine.begin() as conn:
        conn.execute(text(sql))
    print(f"  applied {path}")


def main():
    print(f"Target database: {config.DATABASE_URL.split('@')[-1]}")
    if "localhost" in config.DATABASE_URL:
        print("WARNING: DATABASE_URL still points at localhost. Set it to your cloud DB first.")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            return
    print("1) Applying schema + migrations ...")
    for f in SQL_FILES:
        try:
            run_sql_file(f)
        except Exception as e:
            print(f"  note on {f}: {e}")  # migrations are idempotent; ignore 'already exists'
    print("2) Generating data ...");  subprocess.run([sys.executable, "-m", "src.generator"], check=True)
    print("3) Seeding logins ...");   subprocess.run([sys.executable, "-m", "src.auth", "--seed"], check=True)
    print("4) Running pipeline ...");  subprocess.run([sys.executable, "-m", "src.pipeline"], check=True)
    print("Cloud database ready.")


if __name__ == "__main__":
    main()