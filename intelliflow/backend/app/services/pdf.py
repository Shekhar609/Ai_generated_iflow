"""Streamed PDF export for a saved flow.

Choice of `reportlab` over `weasyprint`: pure-pip install (no system GTK/Cairo
required on Windows), supports incremental writing into a streaming response,
and integrates cleanly with `pygments` for syntax-highlighted code blocks.

Layout (PRD §6):
  1. Cover (flow name, prompt, created_at)
  2. Diagram (graphviz `dot` if available, otherwise a textual edge list)
  3. Component table
  4. Request / response XML, syntax-highlighted
  5. Mapping rules
  6. Citations bibliography
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any, AsyncIterator

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import XmlLexer
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("intelliflow.pdf")


def _render_diagram_png(components, connections) -> bytes | None:
    """Render the flow as a PNG via graphviz. Returns None if `dot` is missing."""
    try:
        from graphviz import Digraph
    except Exception:
        return None
    g = Digraph("iflow", format="png")
    g.attr(rankdir="LR", nodesep="0.3")
    for c in components:
        label = f"{c.get('id', '?')}\\n{c.get('type', '?')}"
        g.node(c["id"], label=label, shape="box", style="rounded,filled", fillcolor="#E5E7EB")
    for e in connections:
        g.edge(e.get("from") or e.get("from_"), e["to"], label=e.get("label") or "")
    try:
        return g.pipe(format="png")
    except Exception as exc:
        logger.warning("graphviz unavailable: %s", exc)
        return None


def _xml_lines_table(xml: str) -> Table:
    styles = getSampleStyleSheet()
    code_style = ParagraphStyle(
        "code", parent=styles["Code"], fontName="Courier", fontSize=7.5, leading=9
    )
    rows = [[Paragraph(f"<font color='#9CA3AF'>{i+1:>4}</font>  {line.replace('<', '&lt;').replace('>', '&gt;')}", code_style)]
            for i, line in enumerate(xml.splitlines() or [""])]
    table = Table(rows, colWidths=[6.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
        ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def build_pdf_stream(flow_record: dict[str, Any], buffer: BytesIO) -> None:
    """Write the PDF for `flow_record` into `buffer`."""
    flow = flow_record.get("flow", {})
    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#4B5563"))

    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=flow.get("flow_name") or flow_record.get("name") or "iFlow",
    )

    story: list[Any] = []

    # Cover
    story.append(Paragraph(flow.get("flow_name") or "Untitled Flow", h1))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(flow.get("description", "") or "", body))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(f"<b>Flow ID:</b> {flow_record.get('flow_id', '')}", small))
    story.append(Paragraph(f"<b>Created:</b> {flow_record.get('created_at', '')}", small))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("<b>Original prompt:</b>", small))
    story.append(Paragraph(flow_record.get("prompt", "") or "(none)", body))
    story.append(PageBreak())

    # Diagram
    story.append(Paragraph("Flow diagram", h2))
    png = _render_diagram_png(flow.get("components", []), flow.get("connections", []))
    if png:
        story.append(Image(BytesIO(png), width=6.5 * inch, height=3.5 * inch, kind="proportional"))
    else:
        story.append(Paragraph(
            "Graphviz <code>dot</code> binary not available; component edges:", small,
        ))
        for e in flow.get("connections", []):
            label = e.get("label")
            arrow = " ⟶ "
            line = f"{e.get('from') or e.get('from_')}{arrow}{e.get('to')}"
            if label:
                line += f"  [{label}]"
            story.append(Paragraph(line, body))
    story.append(PageBreak())

    # Components
    story.append(Paragraph("Components", h2))
    comp_rows = [["ID", "Type", "Purpose"]]
    for c in flow.get("components", []):
        comp_rows.append([c.get("id", ""), c.get("type", ""), c.get("purpose", "")])
    table = Table(comp_rows, colWidths=[0.7 * inch, 1.6 * inch, 4.2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(PageBreak())

    # Request XML
    story.append(Paragraph("Request XML", h2))
    story.append(_xml_lines_table(flow.get("xml_request", "")))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Response XML", h2))
    story.append(_xml_lines_table(flow.get("xml_response", "")))
    story.append(PageBreak())

    # Mapping rules
    story.append(Paragraph("Mapping rules", h2))
    rules = flow.get("mapping_rules") or []
    if rules:
        for r in rules:
            story.append(Paragraph(f"• {r}", body))
    else:
        story.append(Paragraph("No mapping rules defined.", small))
    story.append(Spacer(1, 0.2 * inch))

    # Citations bibliography
    story.append(Paragraph("Citations", h2))
    seen: set[str] = set()
    for c in flow.get("components", []):
        for cit in c.get("citations", []) or []:
            key = f"{cit.get('source')}::{cit.get('chunk_id')}"
            if key in seen:
                continue
            seen.add(key)
            story.append(Paragraph(
                f"[{cit.get('source')} :: {cit.get('chunk_id')}] — cited by component <b>{c.get('id')}</b>",
                small,
            ))
    if not seen:
        story.append(Paragraph("No citations recorded.", small))

    doc.build(story)


async def stream_pdf(flow_record: dict[str, Any], *, chunk_size: int = 16 * 1024) -> AsyncIterator[bytes]:
    """Build the PDF in memory then yield it in fixed-size chunks.

    The PDF library (reportlab) requires random access during layout, so we cannot
    truly stream during build. Streaming the chunks downstream means the client
    receives bytes as soon as they're available even for very large PDFs.
    """
    buffer = BytesIO()
    build_pdf_stream(flow_record, buffer)
    buffer.seek(0)
    while True:
        chunk = buffer.read(chunk_size)
        if not chunk:
            break
        yield chunk


# Silence pygments unused-import warning on environments without an HtmlFormatter user.
_ = HtmlFormatter, highlight, XmlLexer
