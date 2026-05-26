import os
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from src.config import settings


# ── Style helpers ────────────────────────────────────────────────────────────

def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("Cover", parent=s["Title"], fontSize=28, spaceAfter=12,
                         textColor=colors.HexColor("#1a3c5e"), alignment=TA_CENTER))
    s.add(ParagraphStyle("SubCover", parent=s["Normal"], fontSize=14, spaceAfter=6,
                         textColor=colors.HexColor("#4a6fa5"), alignment=TA_CENTER))
    s.add(ParagraphStyle("SectionTitle", parent=s["Heading1"], fontSize=16, spaceAfter=8,
                         textColor=colors.HexColor("#1a3c5e")))
    s.add(ParagraphStyle("SubSection", parent=s["Heading2"], fontSize=12, spaceAfter=6,
                         textColor=colors.HexColor("#2e6da4")))
    s.add(ParagraphStyle("Body", parent=s["Normal"], fontSize=10, spaceAfter=4,
                         leading=14))
    s.add(ParagraphStyle("BulletItem", parent=s["Normal"], fontSize=10, spaceAfter=2,
                         leftIndent=16, bulletIndent=8, leading=14))
    s.add(ParagraphStyle("Warning", parent=s["Normal"], fontSize=10, spaceAfter=4,
                         textColor=colors.HexColor("#cc4400")))
    return s


def _hr(story):
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 6))


def _section_header(story, title: str, s):
    story.append(Spacer(1, 12))
    story.append(Paragraph(title, s["SectionTitle"]))
    _hr(story)


def _bullet(story, text: str, s):
    story.append(Paragraph(f"• {text}", s["BulletItem"]))


# ── Section builders ─────────────────────────────────────────────────────────

def _cover_page(story, prefs: dict, s):
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("✈ AI Trip Planner", s["Cover"]))
    story.append(Spacer(1, 0.2 * inch))

    dest = prefs.get("destination", "Your Destination")
    origin = prefs.get("origin", "")
    start = prefs.get("start_date", "")
    end = prefs.get("end_date", "")
    travelers = prefs.get("travelers", 1)
    trip_type = prefs.get("trip_type", "leisure").title()
    budget = prefs.get("budget_usd", "N/A")

    story.append(Paragraph(f"{origin} → {dest}", s["SubCover"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"{start}  to  {end}", s["SubCover"]))
    story.append(Spacer(1, 0.3 * inch))

    data = [
        ["Travelers", str(travelers)],
        ["Trip Type", trip_type],
        ["Budget", f"${budget:,.0f} USD" if isinstance(budget, (int, float)) else str(budget)],
        ["Generated On", date.today().strftime("%B %d, %Y")],
    ]
    table = Table(data, colWidths=[2 * inch, 3 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f0fe")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f8ff")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(PageBreak())


def _transport_section(story, transport: dict, s):
    _section_header(story, "Section 1 — Flights & Transport", s)

    if not transport:
        story.append(Paragraph("Transport information not available.", s["Warning"]))
        return

    rec = transport.get("recommended", {})
    if rec:
        story.append(Paragraph("Recommended Option", s["SubSection"]))
        for k, v in rec.items():
            story.append(Paragraph(f"{k.replace('_', ' ').title()}: {v}", s["Body"]))
        story.append(Spacer(1, 6))

    cost = transport.get("estimated_cost_usd")
    if cost:
        story.append(Paragraph(f"Estimated Transport Cost: ${cost:,.0f} USD", s["Body"]))

    outbound = transport.get("outbound_options", [])
    if outbound:
        story.append(Paragraph("Outbound Options", s["SubSection"]))
        for opt in outbound[:3]:
            if isinstance(opt, dict):
                _bullet(story, " | ".join(f"{k}: {v}" for k, v in opt.items() if v), s)
            else:
                _bullet(story, str(opt), s)

    notes = transport.get("notes", "")
    if notes:
        story.append(Spacer(1, 6))
        story.append(Paragraph(notes, s["Body"]))


def _hotel_section(story, hotel: dict, s):
    _section_header(story, "Section 2 — Hotel Details", s)

    if not hotel:
        story.append(Paragraph("Hotel information not available.", s["Warning"]))
        return

    rec = hotel.get("recommended", {})
    if rec:
        story.append(Paragraph("Recommended Hotel", s["SubSection"]))
        for k, v in rec.items():
            story.append(Paragraph(f"{k.replace('_', ' ').title()}: {v}", s["Body"]))
        story.append(Spacer(1, 6))

    cost = hotel.get("estimated_cost_usd")
    if cost:
        story.append(Paragraph(f"Estimated Hotel Cost: ${cost:,.0f} USD", s["Body"]))

    options = hotel.get("options", [])
    if options:
        story.append(Paragraph("Other Options", s["SubSection"]))
        for opt in options[:4]:
            if isinstance(opt, dict):
                name = opt.get("name", "Option")
                price = opt.get("price_per_night_usd", "")
                rating = opt.get("rating", "")
                desc = f"{name}"
                if price:
                    desc += f" — ${price}/night"
                if rating:
                    desc += f" — ⭐ {rating}"
                _bullet(story, desc, s)
            else:
                _bullet(story, str(opt), s)


def _itinerary_section(story, itinerary: dict, s):
    _section_header(story, "Section 3 — Day-wise Itinerary", s)

    if not itinerary:
        story.append(Paragraph("Itinerary not available.", s["Warning"]))
        return

    days = itinerary.get("days", [])
    for day_info in days:
        day_num = day_info.get("day", "?")
        day_date = day_info.get("date", "")
        story.append(Paragraph(f"Day {day_num} — {day_date}", s["SubSection"]))

        for period in ["morning", "afternoon", "evening"]:
            activities = day_info.get(period, [])
            if activities:
                story.append(Paragraph(f"{period.title()}:", s["Body"]))
                if isinstance(activities, list):
                    for a in activities:
                        _bullet(story, str(a), s)
                else:
                    _bullet(story, str(activities), s)

        meals = day_info.get("meals", [])
        if meals:
            story.append(Paragraph("Meals:", s["Body"]))
            for m in meals:
                _bullet(story, str(m), s)

        hotel_name = day_info.get("hotel", "")
        if hotel_name:
            story.append(Paragraph(f"Stay: {hotel_name}", s["Body"]))

        transport_note = day_info.get("transport_notes", "")
        if transport_note:
            story.append(Paragraph(f"Transport: {transport_note}", s["Body"]))

        story.append(Spacer(1, 8))

    conflicts = itinerary.get("conflicts", [])
    if conflicts:
        story.append(Paragraph("Notes & Adjustments", s["SubSection"]))
        for c in conflicts:
            story.append(Paragraph(f"⚠ {c}", s["Warning"]))


def _budget_section(story, budget: dict, s):
    _section_header(story, "Section 4 — Budget Report", s)

    if not budget:
        story.append(Paragraph("Budget information not available.", s["Warning"]))
        return

    data = [
        ["Category", "Cost (USD)"],
        ["Transport", f"${budget.get('transport_cost', 0):,.0f}"],
        ["Hotel / Accommodation", f"${budget.get('hotel_cost', 0):,.0f}"],
        ["Activities & Sightseeing", f"${budget.get('activities_cost', 0):,.0f}"],
        ["Food & Dining", f"${budget.get('food_cost', 0):,.0f}"],
        ["Miscellaneous", f"${budget.get('misc_cost', 0):,.0f}"],
        ["TOTAL SPENT", f"${budget.get('total_spent', 0):,.0f}"],
        ["Budget", f"${budget.get('total_budget', 0):,.0f}"],
        ["Remaining", f"${budget.get('remaining', 0):,.0f}"],
    ]

    table = Table(data, colWidths=[3 * inch, 2 * inch])
    within = budget.get("within_budget", True)
    total_row_color = colors.HexColor("#d4edda") if within else colors.HexColor("#f8d7da")

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -3), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -3), (-1, -1), total_row_color),
        ("ROWBACKGROUNDS", (0, 1), (-1, -4), [colors.white, colors.HexColor("#f5f8ff")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story.append(table)

    optimizations = budget.get("optimizations", [])
    if optimizations:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Cost-Saving Tips", s["SubSection"]))
        for tip in optimizations:
            _bullet(story, str(tip), s)


def _packing_section(story, prefs: dict, weather: dict, s):
    _section_header(story, "Section 5 — Packing Checklist", s)

    trip_type = prefs.get("trip_type", "leisure")
    has_rain = weather.get("rain_days", 0) > 0
    travelers = prefs.get("travelers", 1)

    essentials = [
        "Passport / ID & travel documents",
        "Travel insurance documents",
        "Phone charger & power bank",
        "Credit/debit cards & some local cash",
        "Prescription medications",
    ]
    clothing = [
        "Comfortable walking shoes",
        "Light clothing (3–4 sets per person)",
        "Formal outfit (if dining out / business)",
    ]
    if has_rain:
        clothing.append("Rain jacket / compact umbrella")
    extras_by_type = {
        "beach": ["Sunscreen SPF 50+", "Sunglasses", "Swimwear", "Beach towel", "Flip-flops"],
        "adventure": ["Trekking shoes", "First-aid kit", "Insect repellent", "Headlamp"],
        "business": ["Laptop & charger", "Business cards", "Professional attire"],
        "family": ["Children's snacks", "First-aid kit", "Baby essentials if applicable"],
        "honeymoon": ["Formal evening wear", "Romantic extras"],
    }
    extras = extras_by_type.get(trip_type, ["Camera & memory card"])

    story.append(Paragraph("Essentials", s["SubSection"]))
    for item in essentials:
        _bullet(story, item, s)

    story.append(Paragraph("Clothing", s["SubSection"]))
    for item in clothing:
        _bullet(story, item, s)

    story.append(Paragraph("Trip-Specific", s["SubSection"]))
    for item in extras:
        _bullet(story, item, s)


def _emergency_section(story, destination: str, s):
    _section_header(story, "Section 6 — Emergency Contacts", s)

    story.append(Paragraph(
        "Save these numbers before you travel. Check local emergency numbers "
        "for your specific destination country.",
        s["Body"],
    ))
    story.append(Spacer(1, 8))

    contacts = [
        ["Service", "Number / Info"],
        ["Local Police / Emergency", "112 (most countries) or local equivalent"],
        ["Ambulance", "112 or local emergency number"],
        ["Your Country's Embassy", "Check travel.gov or equivalent before departure"],
        ["Travel Insurance Helpline", "See your policy document"],
        ["Hotel Front Desk", "Ask on check-in"],
        ["Local Tourist Helpline", f"Search 'tourist helpline {destination}'"],
    ]

    table = Table(contacts, colWidths=[2.5 * inch, 3.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8ff")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)


# ── Public entry point ───────────────────────────────────────────────────────

def generate_pdf(state: dict) -> str:
    """Build the full trip report PDF. Returns the saved file path."""
    prefs = state.get("trip_preferences", {})
    session_id = state.get("session_id", "unknown")
    warnings = state.get("review_status", {}).get("warnings", [])

    os.makedirs(settings.pdf_output_dir, exist_ok=True)
    file_path = os.path.join(settings.pdf_output_dir, f"trip_{session_id}.pdf")

    doc = SimpleDocTemplate(
        file_path, pagesize=A4,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=inch, bottomMargin=0.75 * inch,
    )
    s = _styles()
    story = []

    _cover_page(story, prefs, s)
    _transport_section(story, state.get("transport_data", {}), s)
    story.append(PageBreak())
    _hotel_section(story, state.get("hotel_data", {}), s)
    story.append(PageBreak())
    _itinerary_section(story, state.get("itinerary", {}), s)
    story.append(PageBreak())
    _budget_section(story, state.get("budget_summary", {}), s)
    story.append(PageBreak())
    _packing_section(story, prefs, state.get("weather_data", {}), s)
    story.append(PageBreak())
    _emergency_section(story, prefs.get("destination", "your destination"), s)

    if warnings:
        story.append(PageBreak())
        _section_header(story, "Planner Notes & Warnings", s)
        for w in warnings:
            story.append(Paragraph(f"⚠ {w}", s["Warning"]))

    doc.build(story)
    return file_path
