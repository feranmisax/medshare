from pathlib import Path
from sqlalchemy import text
from src import db

sql = Path("db/migrate_expiry.sql").read_text(encoding="utf-8")
with db.engine.begin() as conn:
    conn.execute(text(sql))
print("migrate_expiry.sql applied successfully")