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


def build_pdf(pid, label):
    """Render a one-page PDF report for the pharmacy; returns PDF bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

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

    story.append(Paragraph("MedShare — Pharmacy Report", h))
    story.append(Paragraph(f"{label} &nbsp;·&nbsp; generated {date.today():%d %b %Y}", sub))
    story.append(Spacer(1, 8))

    def naira(x):
        return f"NGN {x:,.0f}"

    # headline metrics table
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
    t = Table(headline, colWidths=[90 * mm, 70 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F3")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D1C4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # top sellers
    story.append(Paragraph("Top 5 best-selling drugs (last 90 days)", sec))
    if m["top_sellers"].empty:
        story.append(Paragraph("No sales recorded in the period.", sub))
    else:
        rows = [["Drug", "Units sold"]] + [[r["drug"], f"{int(r['units']):,}"]
                                           for _, r in m["top_sellers"].iterrows()]
        t2 = Table(rows, colWidths=[110 * mm, 50 * mm])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4F0EC")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D1C4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t2)

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
    story.append(Paragraph(
        "Figures are computed live from the MedShare database at the time of generation. "
        "The operational rescue ratio is an in-app measure of value redistributed versus value "
        "lost to expiry, specific to this pharmacy.", sub))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
