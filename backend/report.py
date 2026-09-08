from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_report(result: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="GeoAI Deforestation Report",
        author="WebGIS Deforestation",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("GeoAI Deforestation Analysis", styles["Title"]),
        Paragraph("Landsat-based forest screening using the supplied GEE workflow", styles["Normal"]),
        Spacer(1, 5 * mm),
    ]

    summary = [
        ["AOI area", f"{result.get('aoi_area_ha', 0):,.2f} ha"],
        ["Baseline forest (1990)", f"{result.get('baseline_area_ha', 0):,.2f} ha"],
        ["Current forest (2020)", f"{result.get('current_area_ha', 0):,.2f} ha"],
        ["Change 1990 → 2020", f"{result.get('change_ha', 0):,.2f} ha"],
        ["Current forest cover", _pct(result.get("forest_cover_pct"))],
    ]
    table = Table(summary, colWidths=[65 * mm, 95 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E9EEF6")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B6C1D0")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([table, Spacer(1, 6 * mm)])

    story.append(Paragraph("Forest area by benchmark year", styles["Heading2"]))
    area_rows = [["Year", "Forest area (ha)"]]
    for year in result.get("years", []):
        value = result.get("area_by_year", {}).get(year, result.get("area_by_year", {}).get(str(year), 0))
        area_rows.append([str(year), f"{float(value or 0):,.2f}"])
    area_table = Table(area_rows, colWidths=[45 * mm, 70 * mm])
    area_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18243A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B6C1D0")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([area_table, Spacer(1, 6 * mm)])

    story.append(Paragraph("Method", styles["Heading2"]))
    story.append(
        Paragraph(
            "Landsat 4/5 are used before 2014 and Landsat 8/9 from 2014 onward. "
            "Cloud, cirrus and shadow flags follow the supplied QA_PIXEL masks. "
            "Each benchmark uses a median composite over the stated ±1 year window. "
            "The vegetation index is (NIR - SWIR) / (NIR + SWIR), with forest defined at VI > 0.7. "
            "Forest area is derived from pixel area in hectares.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Limit", styles["Heading2"]))
    story.append(
        Paragraph(
            result.get("note", "Remote-sensing screening output."),
            styles["BodyText"],
        )
    )

    doc.build(story)
    return buffer.getvalue()


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):,.2f}%"
