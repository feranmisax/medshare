"""
send_monthly_reports.py — emails the dashboard PDF to every pharmacy that has an
email on file. Intended to run on a schedule (see .github/workflows/monthly_reports.yml).

Reads DATABASE_URL and SMTP_* from environment variables. 
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

import pandas as pd
from src import db, dashboard, emailer


def main():
    if not emailer.is_configured():
        print("ERROR: SMTP_* environment variables are not set. Aborting.")
        sys.exit(1)

    targets = db.read_sql("""
        SELECT pharmacy_id, area, email FROM pharmacies
        WHERE email IS NOT NULL AND email <> '' ORDER BY pharmacy_id
    """)
    if targets.empty:
        print("No pharmacies have an email on file. Nothing to send.")
        return

    # previous calendar month window [first day prev month, first day this month)
    today = pd.Timestamp.today().normalize()
    this_month_start = today.replace(day=1)
    prev_month_end = this_month_start                      # exclusive upper bound
    prev_month_start = (this_month_start - pd.Timedelta(days=1)).replace(day=1)
    period_label = prev_month_start.strftime("%B %Y")
    stamp = prev_month_start.strftime("%Y%m")
    period = (prev_month_start.to_pydatetime(), prev_month_end.to_pydatetime(), period_label)

    sent, failed = 0, 0
    for _, p in targets.iterrows():
        pid = p["pharmacy_id"]
        try:
            pdf = dashboard.build_pdf(pid, f"{pid} · {p['area']}", period=period)
            plain, html = emailer.report_email_body(pid, p["area"], period_label, monthly=True)
            emailer.send_report(
                p["email"], f"MedShare statement — {pid} ({period_label})",
                plain, pdf, f"MedShare_{pid}_{stamp}.pdf", body_html=html)
            print(f"  sent -> {pid} ({p['email']})")
            sent += 1
        except Exception as ex:
            print(f"  FAILED -> {pid}: {ex}")
            failed += 1
    print(f"\nDone. {sent} sent, {failed} failed.")


if __name__ == "__main__":
    main()