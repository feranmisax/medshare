"""
Per-pharmacy management dashboard: live metrics + a downloadable PDF report.

Everything is computed from the database at call time, so the figures always
reflect the current state (they update after every action automatically).

metrics(pharmacy_id) -> dict of headline numbers + small dataframes
build_pdf(pharmacy_id, pharmacy_label) -> bytes (a PDF report)
"""
import io
from datetime import date

import pandas as pd

from src import db


def metrics(pid):
    """Compute all dashboard metrics for one pharmacy, fresh from the DB."""
    m = {}

    # --- stock value & at-risk value ---
    row = db.read_sql("""
        SELECT
          (SELECT COALESCE(SUM(quantity*unit_price),0) FROM inventory_batches
             WHERE pharmacy_id=:p AND is_expired=FALSE AND quantity>0) AS stock_value,
          (SELECT COUNT(*) FROM inventory_batches
             WHERE pharmacy_id=:p AND is_expired=FALSE AND quantity>0) AS batches,
          (SELECT COALESCE(SUM(b.quantity*b.unit_price),0)
             FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id=r.batch_id
             WHERE b.pharmacy_id=:p AND r.score_date=CURRENT_DATE
               AND r.risk_tier IN ('High','Critical')) AS at_risk_value,
          (SELECT COUNT(*) FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id=r.batch_id
             WHERE b.pharmacy_id=:p AND r.score_date=CURRENT_DATE
               AND r.risk_tier IN ('High','Critical')) AS at_risk_batches
    """, {"p": pid}).iloc[0]
    m["stock_value"] = float(row["stock_value"])
    m["batches"] = int(row["batches"])
    m["at_risk_value"] = float(row["at_risk_value"])
    m["at_risk_batches"] = int(row["at_risk_batches"])

    # --- redistribution / revenue / waste for this pharmacy ---
    row2 = db.read_sql("""
        SELECT
          (SELECT COALESCE(SUM(t.gross_value),0) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE rr.source_pharmacy_id=:p AND t.status='ACCEPTED') AS value_sold,
          (SELECT COALESCE(SUM(t.gross_value),0) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE rr.target_pharmacy_id=:p AND t.status='ACCEPTED') AS value_bought,
          (SELECT COUNT(*) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE (rr.source_pharmacy_id=:p OR rr.target_pharmacy_id=:p) AND t.status='ACCEPTED') AS transfers,
          (SELECT COALESCE(SUM(value_lost),0) FROM expired_stock WHERE pharmacy_id=:p) AS waste_value,
          (SELECT COUNT(*) FROM expired_stock WHERE pharmacy_id=:p) AS waste_batches
    """, {"p": pid}).iloc[0]
    m["value_sold"] = float(row2["value_sold"])
    m["value_bought"] = float(row2["value_bought"])
    m["transfers"] = int(row2["transfers"])
    m["waste_value"] = float(row2["waste_value"])
    m["waste_batches"] = int(row2["waste_batches"])

    # --- top 5 best-selling drugs (by units sold, last 90 days) ---
    m["top_sellers"] = db.read_sql("""
        SELECT d.name AS drug, SUM(s.units_sold) AS units
        FROM sales_daily s JOIN drugs d ON d.drug_id=s.drug_id
        WHERE s.pharmacy_id=:p AND s.sale_date >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY d.name ORDER BY units DESC LIMIT 5
    """, {"p": pid})

    # --- stock value by category (for a chart) ---
    m["by_category"] = db.read_sql("""
        SELECT d.category, SUM(b.quantity*b.unit_price) AS value
        FROM inventory_batches b JOIN drugs d ON d.drug_id=b.drug_id
        WHERE b.pharmacy_id=:p AND b.is_expired=FALSE AND b.quantity>0
        GROUP BY d.category ORDER BY value DESC
    """, {"p": pid})

    # --- waste-prevention ratio (operational, in-app) ---
    rescued = m["value_sold"] + m["value_bought"]
    denom = rescued + m["waste_value"]
    m["rescue_ratio"] = (rescued / denom) if denom else None
    return m


def period_metrics(pid, start, end):
    """Metrics for a calendar period [start, end) — a true monthly statement.

    Activity figures (transfers, revenue, waste logged, units sold, best-sellers)
    are bounded to the period. Position figures (current stock value, value at
    risk) are inherently 'as of now' and are returned as the current snapshot,
    labelled as such in the report.
    """
    m = {"period_start": start, "period_end": end}

    # position figures — current snapshot (no such thing as "stock value during June")
    snap = metrics(pid)
    m["stock_value"] = snap["stock_value"]
    m["batches"] = snap["batches"]
    m["at_risk_value"] = snap["at_risk_value"]
    m["at_risk_batches"] = snap["at_risk_batches"]

    # activity figures — bounded to [start, end)
    row = db.read_sql("""
        SELECT
          (SELECT COALESCE(SUM(t.gross_value),0) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE rr.source_pharmacy_id=:p AND t.status='ACCEPTED'
               AND t.created_at >= :s AND t.created_at < :e) AS value_sold,
          (SELECT COALESCE(SUM(t.gross_value),0) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE rr.target_pharmacy_id=:p AND t.status='ACCEPTED'
               AND t.created_at >= :s AND t.created_at < :e) AS value_bought,
          (SELECT COUNT(*) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE (rr.source_pharmacy_id=:p OR rr.target_pharmacy_id=:p) AND t.status='ACCEPTED'
               AND t.created_at >= :s AND t.created_at < :e) AS transfers,
          (SELECT COALESCE(SUM(commission_amount),0) FROM transfers t
             JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
             WHERE (rr.source_pharmacy_id=:p OR rr.target_pharmacy_id=:p) AND t.status='ACCEPTED'
               AND t.created_at >= :s AND t.created_at < :e) AS commission,
          (SELECT COALESCE(SUM(value_lost),0) FROM expired_stock
             WHERE pharmacy_id=:p AND logged_at >= :s AND logged_at < :e) AS waste_value,
          (SELECT COUNT(*) FROM expired_stock
             WHERE pharmacy_id=:p AND logged_at >= :s AND logged_at < :e) AS waste_batches,
          (SELECT COALESCE(SUM(units_sold),0) FROM sales_daily
             WHERE pharmacy_id=:p AND sale_date >= :s AND sale_date < :e) AS units_sold,
          (SELECT COALESCE(SUM(units_sold * unit_price),0) FROM sales_daily
             WHERE pharmacy_id=:p AND sale_date >= :s AND sale_date < :e) AS sales_value
    """, {"p": pid, "s": start, "e": end}).iloc[0]
    m["value_sold"] = float(row["value_sold"])
    m["value_bought"] = float(row["value_bought"])
    m["transfers"] = int(row["transfers"])
    m["commission"] = float(row["commission"])
    m["waste_value"] = float(row["waste_value"])
    m["waste_batches"] = int(row["waste_batches"])
    m["units_sold"] = int(row["units_sold"])
    m["sales_value"] = float(row["sales_value"])

    # best sellers within the period
    m["top_sellers"] = db.read_sql("""
        SELECT d.name AS drug, SUM(s.units_sold) AS units
        FROM sales_daily s JOIN drugs d ON d.drug_id=s.drug_id
        WHERE s.pharmacy_id=:p AND s.sale_date >= :s AND s.sale_date < :e
        GROUP BY d.name ORDER BY units DESC LIMIT 5
    """, {"p": pid, "s": start, "e": end})

    # current stock by category (position, snapshot)
    m["by_category"] = snap["by_category"]

    rescued = m["value_sold"] + m["value_bought"]
    denom = rescued + m["waste_value"]
    m["rescue_ratio"] = (rescued / denom) if denom else None
    return m


def build_pdf(pid, label, period=None):
    """Render a one-page PDF report for the pharmacy; returns PDF bytes.

    period=None  -> current snapshot (on-demand download/email).
    period=(start, end, "June 2026") -> true monthly statement: activity figures
       are bounded to [start, end); position figures (stock value, value at risk)
       remain a current snapshot, labelled distinctly.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    if period is not None:
        start, end, period_label = period
        m = period_metrics(pid, start, end)
    else:
        period_label = None
        m = metrics(pid)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()
    BRAND = colors.HexColor("#0F6E5C")
    h = ParagraphStyle("h", parent=styles["Title"], textColor=BRAND, fontSize=20, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=colors.HexColor("#3D544D"), fontSize=10)
    sec = ParagraphStyle("sec", parent=styles["Heading2"], textColor=BRAND, fontSize=12, spaceBefore=14, spaceAfter=6)
    story = []

    def naira(x):
        return f"NGN {x:,.0f}"

    def styled(rows):
        tb = Table(rows, colWidths=[90 * mm, 70 * mm])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F3")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D1C4")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return tb

    def sellers_table(df):
        rows = [["Drug", "Units sold"]] + [[r["drug"], f"{int(r['units']):,}"] for _, r in df.iterrows()]
        tb = Table(rows, colWidths=[110 * mm, 50 * mm])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4F0EC")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D1C4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return tb

    if period_label:
        from reportlab.platypus import PageBreak
        # ===== PAGE 1 — the chosen period (a calendar month from the email, or a custom range from the app) =====
        story.append(Paragraph("MedShare — Period Report", h))
        story.append(Paragraph(f"{label} &nbsp;·&nbsp; {period_label} &nbsp;·&nbsp; "
                               f"generated {date.today():%d %b %Y}", sub))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Activity over {period_label}", sec))
        act = [["Metric", "Value"],
               ["Value redistributed (sold)", naira(m["value_sold"])],
               ["Value received (bought)", naira(m["value_bought"])],
               ["Completed transfers", f"{m['transfers']:,}"],
               ["Commission paid", naira(m["commission"])],
               ["Units sold", f"{m['units_sold']:,}"],
               ["Sales value", naira(m["sales_value"])],
               ["Value lost to expiry", naira(m["waste_value"])],
               ["Batches expired", f"{m['waste_batches']:,}"]]
        if m["rescue_ratio"] is not None:
            act.append(["Operational rescue ratio (this period)", f"{m['rescue_ratio']*100:.0f}%"])
        story.append(styled(act))
        story.append(Paragraph(f"Top 5 best-selling drugs ({period_label})", sec))
        if m["top_sellers"].empty:
            story.append(Paragraph("No sales recorded in the period.", sub))
        else:
            story.append(sellers_table(m["top_sellers"]))
        story.append(Spacer(1, 14))
        story.append(Paragraph(
            f"This page covers activity over {period_label}. "
            "Page 2 shows the all-time summary and current position as at the generation date.", sub))

        # ===== PAGE 2 — all-time, up to the send date =====
        a = metrics(pid)  # un-bounded = cumulative / all-time + current position
        story.append(PageBreak())
        story.append(Paragraph("MedShare — All-Time Summary", h))
        story.append(Paragraph(f"{label} &nbsp;·&nbsp; up to {date.today():%d %b %Y}", sub))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Current position (as of today)", sec))
        pos = [["Metric", "Value"],
               ["Total stock value", naira(a["stock_value"])],
               ["Batches in stock", f"{a['batches']:,}"],
               ["Value at risk of expiry", naira(a["at_risk_value"])],
               ["Batches at risk", f"{a['at_risk_batches']:,}"]]
        story.append(styled(pos))
        story.append(Paragraph("All-time activity (since launch)", sec))
        alltime = [["Metric", "Value"],
                   ["Value redistributed (sold)", naira(a["value_sold"])],
                   ["Value received (bought)", naira(a["value_bought"])],
                   ["Completed transfers", f"{a['transfers']:,}"],
                   ["Value lost to expiry", naira(a["waste_value"])],
                   ["Batches expired", f"{a['waste_batches']:,}"]]
        if a["rescue_ratio"] is not None:
            alltime.append(["Operational rescue ratio (all-time)", f"{a['rescue_ratio']*100:.0f}%"])
        story.append(styled(alltime))
        story.append(Paragraph("Top 5 best-selling drugs (last 90 days)", sec))
        if a["top_sellers"].empty:
            story.append(Paragraph("No recent sales recorded.", sub))
        else:
            story.append(sellers_table(a["top_sellers"]))
        story.append(Spacer(1, 14))
        story.append(Paragraph(
            "All-time figures are cumulative since the platform began operating for this pharmacy. "
            "Current-position figures are a snapshot as at the generation date. The operational "
            "rescue ratio is an in-app measure of value redistributed versus value lost to expiry.", sub))
        doc.build(story)
        buf.seek(0)
        return buf.getvalue()

    # ===== snapshot mode (on-demand button) — single page =====
    story.append(Paragraph("MedShare — Pharmacy Report", h))
    story.append(Paragraph(f"{label} &nbsp;·&nbsp; generated {date.today():%d %b %Y}", sub))
    story.append(Spacer(1, 8))
    headline = [
        ["Metric", "Value"],
        ["Total stock value", naira(m["stock_value"])],
        ["Batches in stock", f"{m['batches']:,}"],
        ["Value at risk of expiry", naira(m["at_risk_value"])],
        ["Batches at risk", f"{m['at_risk_batches']:,}"],
        ["Value redistributed (sold)", naira(m["value_sold"])],
        ["Value received (bought)", naira(m["value_bought"])],
        ["Completed transfers", f"{m['transfers']:,}"],
        ["Value lost to expiry", naira(m["waste_value"])],
    ]
    if m["rescue_ratio"] is not None:
        headline.append(["Operational rescue ratio", f"{m['rescue_ratio']*100:.0f}%"])
    story.append(styled(headline))

    # top sellers
    story.append(Paragraph("Top 5 best-selling drugs (last 90 days)", sec))
    if m["top_sellers"].empty:
        story.append(Paragraph("No sales recorded in the period.", sub))
    else:
        story.append(sellers_table(m["top_sellers"]))

    # stock by category
    story.append(Paragraph("Stock value by category", sec))
    if m["by_category"].empty:
        story.append(Paragraph("No stock recorded.", sub))
    else:
        rows = [["Category", "Value"]] + [[r["category"], naira(float(r["value"]))]
                                          for _, r in m["by_category"].iterrows()]
        t3 = Table(rows, colWidths=[110 * mm, 50 * mm])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4F0EC")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D1C4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t3)

    story.append(Spacer(1, 16))
    if period_label:
        note = (f"Activity figures cover {period_label}. Current-position figures (stock value, "
                "value at risk) are a snapshot as of the generation date. The operational rescue "
                "ratio is an in-app measure of value redistributed versus value lost to expiry "
                "within the period, specific to this pharmacy.")
    else:
        note = ("Figures are computed live from the MedShare database at the time of generation. "
                "The operational rescue ratio is an in-app measure of value redistributed versus "
                "value lost to expiry, specific to this pharmacy.")
    story.append(Paragraph(note, sub))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()