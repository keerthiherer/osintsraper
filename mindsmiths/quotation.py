"""Scope-based quotation assistant and print-ready quote documents.

The recommendation uses the requested project scope. Business size may influence
the package suggestion but never automatically inflates the price.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO
from typing import Any

from config import Settings
from .pricing import PricingCatalogue
from .revenue import RevenueAssessment

WEBSITE_TYPES = {
    "landing": "Landing page",
    "static": "Static website",
    "business": "Business website",
    "dynamic": "Dynamic website",
    "ecommerce": "E-commerce website",
}

FEATURES = {
    "booking_enquiry": "Booking or enquiry functionality",
    "cms_admin": "CMS / admin panel",
    "custom_integration": "Custom integration",
    "content_page": "Content creation (per page)",
    "seo_setup": "SEO setup",
    "additional_support": "Additional support package",
}


@dataclass
class QuoteScope:
    website_type: str = "business"
    pages: int = 5
    features: list[str] = field(default_factory=list)
    content_pages: int = 0
    integrations: int = 0
    maintenance_months: int = 0
    include_hosting_domain: bool = False
    additional_support_hours: int = 0
    timeline_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteRecommendation:
    package_name: str
    min_price: int
    max_price: int
    delivery_days: int
    maintenance_monthly: int
    maintenance_total: int
    hosting_domain: int
    effort: str
    budget_fit: str
    line_items: list[dict[str, Any]] = field(default_factory=list)
    addons: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_scope(record: dict[str, Any], revenue: RevenueAssessment) -> QuoteScope:
    website_type = "business"
    features: list[str] = []
    if record.get("website_status") == "No website listed":
        website_type = "landing" if revenue.affordability == "limited" else "business"
    if record.get("website_status") in {"Website unreachable", "Website check failed"}:
        website_type = "business"
    if record.get("catalogue_size") and int(record["catalogue_size"]) >= 30:
        website_type = "ecommerce"
    if record.get("has_booking") or record.get("has_enquiry"):
        features.append("booking_enquiry")
    if website_type in {"business", "dynamic", "ecommerce"}:
        features.append("cms_admin")
    return QuoteScope(
        website_type=website_type,
        pages=5,
        features=features,
        integrations=0,
        maintenance_months=3,
        include_hosting_domain=False,
    )


def recommend_quote(
    record: dict[str, Any],
    revenue: RevenueAssessment,
    scope: QuoteScope,
    catalogue: PricingCatalogue,
) -> QuoteRecommendation:
    website_type = scope.website_type if scope.website_type in WEBSITE_TYPES else "business"
    clean_features = [feature for feature in scope.features if feature in FEATURES]
    pages = max(1, int(scope.pages or 1))

    base = catalogue.base_price(website_type)
    line_items = [{"label": f"{WEBSITE_TYPES[website_type]} base package", "amount": base}]
    subtotal = base

    extra_pages = max(0, pages - int(catalogue.included_pages))
    if extra_pages:
        amount = extra_pages * int(catalogue.per_extra_page)
        subtotal += amount
        line_items.append({"label": f"{extra_pages} extra page(s)", "amount": amount})

    for feature in clean_features:
        if feature == "content_page":
            amount = max(0, int(scope.content_pages)) * int(catalogue.feature_prices.get("content_page", 2000))
            label = f"Content creation ({scope.content_pages} page(s))"
        elif feature == "custom_integration":
            amount = max(1, int(scope.integrations)) * int(catalogue.feature_prices.get("custom_integration", 10000))
            label = f"Custom integrations ({max(1, int(scope.integrations))})"
        elif feature == "additional_support":
            amount = max(1, int(scope.additional_support_hours)) * int(catalogue.feature_prices.get("additional_support", 3000))
            label = f"Additional support ({max(1, int(scope.additional_support_hours))} hour(s))"
        else:
            amount = int(catalogue.feature_prices.get(feature, 0))
            label = FEATURES[feature]
        if amount:
            subtotal += amount
            line_items.append({"label": label, "amount": amount})

    low = max(int(catalogue.minimum_project_price), int(round(subtotal * 0.92, -2)))
    high = min(int(catalogue.maximum_project_price), int(round(subtotal * 1.12, -2)))
    if high < low:
        high = low

    base_days = catalogue.delivery(website_type)
    delivery = base_days + extra_pages * 2 + len(clean_features) * 2
    if scope.timeline_days:
        delivery = max(3, int(scope.timeline_days))

    maintenance_total = max(0, int(scope.maintenance_months)) * int(catalogue.maintenance_monthly)
    hosting = int(catalogue.hosting_domain_annual) if scope.include_hosting_domain else 0
    if hosting:
        line_items.append({"label": "Hosting and domain (annual)", "amount": hosting})
        subtotal += hosting
        high = min(int(catalogue.maximum_project_price), high + hosting)
        low = max(int(catalogue.minimum_project_price), low + hosting)

    feature_count = len(clean_features) + (1 if extra_pages >= 4 else 0)
    if feature_count <= 1 and pages <= 5:
        effort = "Low"
    elif feature_count <= 3 and pages <= 12:
        effort = "Medium"
    else:
        effort = "High"

    package_name = {
        "landing": "Starter Landing Package",
        "static": "Static Presence Package",
        "business": "Business Website Package",
        "dynamic": "Dynamic Business Package",
        "ecommerce": "E-commerce Launch Package",
    }[website_type]

    reasons = [
        f"Scope requested: {WEBSITE_TYPES[website_type]} with {pages} page(s).",
        f"Price is based on the configured catalogue, not on assumed revenue.",
    ]
    if revenue.affordability == "limited":
        reasons.append("Budget fit is limited; the recommendation avoids automatic upselling.")
    elif revenue.affordability == "higher-capability":
        reasons.append("Business-size signals suggest capacity for a larger scope, but scope still drives the quote.")
    else:
        reasons.append("Budget fit is uncertain; confirm requirements and budget before finalising.")
    if clean_features:
        reasons.append("Included features: " + ", ".join(FEATURES[feature] for feature in clean_features) + ".")

    addons = [
        "SEO setup (if not already included)",
        "Additional content pages",
        "Booking/enquiry workflow",
        "E-commerce or catalogue upgrade",
        "Maintenance retainer",
    ]
    if scope.include_hosting_domain:
        addons.append("Hosting/domain already included in this quote")
    if scope.maintenance_months:
        addons.append(f"{scope.maintenance_months}-month maintenance package")

    return QuoteRecommendation(
        package_name=package_name,
        min_price=int(low),
        max_price=int(high),
        delivery_days=int(delivery),
        maintenance_monthly=int(catalogue.maintenance_monthly),
        maintenance_total=int(maintenance_total),
        hosting_domain=int(hosting),
        effort=effort,
        budget_fit=revenue.affordability,
        line_items=line_items,
        addons=addons,
        reasons=reasons,
        exclusions=list(catalogue.exclusions),
        assumptions=list(catalogue.assumptions),
    )


def _inr(value: int | float) -> str:
    return f"INR {float(value):,.0f}"


def _html_rows(quote: QuoteRecommendation, catalogue: PricingCatalogue) -> str:
    rows = "".join(
        f"<tr><td>{escape(str(item['label']))}</td><td class='num'>{_inr(item['amount'])}</td></tr>"
        for item in quote.line_items
    )
    if quote.maintenance_total:
        rows += (
            f"<tr><td>Maintenance ({quote.maintenance_total // max(1, quote.maintenance_monthly)} month(s))</td>"
            f"<td class='num'>{_inr(quote.maintenance_total)}</td></tr>"
        )
    if not quote.hosting_domain:
        rows += "<tr><td>Hosting and domain</td><td class='num'>Excluded (quoted separately)</td></tr>"
    return rows


def build_quote_html(
    client_name: str,
    scope: QuoteScope,
    quote: QuoteRecommendation,
    catalogue: PricingCatalogue,
    *,
    company_name: str = "MindSmiths",
    company_parent: str = "Melouz Technologies Pvt Ltd",
    company_contact: str = "sales@mindsmiths.example",
    company_website: str = "https://mindsmiths.example",
    prepared_on: date | None = None,
) -> str:
    prepared_on = prepared_on or date.today()
    valid_until = prepared_on + timedelta(days=max(1, int(catalogue.validity_days)))
    features = ", ".join(FEATURES.get(feature, feature) for feature in scope.features) or "Core website build"
    milestones = "".join(
        f"<li>{escape(str(item.get('label', '')))} — {item.get('percent', 0)}%</li>"
        for item in catalogue.payment_milestones
    )
    exclusions = "".join(f"<li>{escape(item)}</li>" for item in quote.exclusions)
    assumptions = "".join(f"<li>{escape(item)}</li>" for item in quote.assumptions)
    addons = "".join(f"<li>{escape(item)}</li>" for item in quote.addons)
    reasons = "".join(f"<li>{escape(item)}</li>" for item in quote.reasons)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quotation — {escape(client_name)}</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  body {{ font-family: Arial, Helvetica, sans-serif; color: #1f2937; font-size: 12px; line-height: 1.5; }}
  .brand {{ border-bottom: 3px solid #0f766e; padding-bottom: 12px; margin-bottom: 18px; }}
  .brand h1 {{ margin: 0; color: #0f766e; font-size: 26px; }}
  .brand p {{ margin: 3px 0; color: #475569; }}
  h2 {{ color: #0f766e; font-size: 16px; margin: 22px 0 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 7px 9px; text-align: left; }}
  th {{ background: #f0fdfa; }}
  td.num {{ text-align: right; white-space: nowrap; }}
  .meta td:first-child {{ width: 45%; font-weight: bold; }}
  .notice {{ background: #f8fafc; border-left: 4px solid #0f766e; padding: 10px 12px; margin: 12px 0; }}
  ul {{ margin: 6px 0 6px 18px; padding: 0; }}
  .footer {{ margin-top: 26px; border-top: 1px solid #cbd5e1; padding-top: 10px; color: #64748b; font-size: 10px; }}
  @media print {{ body {{ font-size: 11px; }} .no-print {{ display: none; }} }}
</style></head><body>
<div class="brand">
  <h1>{escape(company_name)}</h1>
  <p>Backed by {escape(company_parent)}</p>
  <p>{escape(company_contact)} · {escape(company_website)}</p>
</div>
<h2>Quotation</h2>
<table class="meta">
  <tr><td>Client business</td><td>{escape(client_name)}</td></tr>
  <tr><td>Prepared on</td><td>{prepared_on.isoformat()}</td></tr>
  <tr><td>Valid until</td><td>{valid_until.isoformat()}</td></tr>
  <tr><td>Recommended package</td><td>{escape(quote.package_name)}</td></tr>
  <tr><td>Budget fit</td><td>{escape(quote.budget_fit)}</td></tr>
  <tr><td>Estimated delivery</td><td>{quote.delivery_days} days after advance and content handover</td></tr>
</table>

<h2>Project scope</h2>
<p><strong>{escape(WEBSITE_TYPES.get(scope.website_type, scope.website_type))}</strong> with {scope.pages} page(s).</p>
<p>{escape(features)}</p>

<h2>Recommended quotation</h2>
<p><strong>{_inr(quote.min_price)} – {_inr(quote.max_price)}</strong> (before applicable taxes)</p>
<table>
  <thead><tr><th>Item</th><th class="num">Amount</th></tr></thead>
  <tbody>{_html_rows(quote, catalogue)}</tbody>
</table>
<p class="notice"><strong>Why this recommendation:</strong><ul>{reasons}</ul></p>
<p class="notice">Business-size evidence is used only as context. The scope above determines the price. This is not a claim about the client's revenue.</p>

<h2>Optional add-ons</h2>
<ul>{addons}</ul>

<h2>Payment milestones</h2>
<ul>{milestones}</ul>

<h2>Maintenance</h2>
<p>{escape('Included: ' + str(quote.maintenance_total // max(1, quote.maintenance_monthly)) + ' month(s) at ' + _inr(quote.maintenance_monthly) + '/month.' if quote.maintenance_total else 'No maintenance package is included in this quotation.')}</p>

<h2>Assumptions</h2>
<ul>{assumptions}</ul>

<h2>Exclusions</h2>
<ul>{exclusions}</ul>

<h2>Next step</h2>
<p>Confirm the scope, share brand assets and content, and approve this quotation to schedule the project. This quotation is valid until {valid_until.isoformat()}.</p>

<div class="footer">
  {escape(company_name)}, backed by {escape(company_parent)}. Prices in {escape(catalogue.currency)}.
  Generated by the MindSmiths Sales Intelligence Platform. No customer-specific discount is applied unless configured by the sales team.
</div>
</body></html>"""


def build_quote_pdf(
    client_name: str,
    scope: QuoteScope,
    quote: QuoteRecommendation,
    catalogue: PricingCatalogue,
    *,
    company_name: str = "MindSmiths",
    company_parent: str = "Melouz Technologies Pvt Ltd",
    company_contact: str = "sales@mindsmiths.example",
    company_website: str = "https://mindsmiths.example",
    prepared_on: date | None = None,
) -> bytes:
    """Build a branded PDF. Requires reportlab (declared in requirements.txt)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    prepared_on = prepared_on or date.today()
    valid_until = prepared_on + timedelta(days=max(1, int(catalogue.validity_days)))
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Quotation - {client_name}", author=company_name,
    )
    styles = getSampleStyleSheet()
    brand = ParagraphStyle("Brand", parent=styles["Title"], textColor=colors.HexColor("#0f766e"), fontSize=24, alignment=TA_LEFT)
    heading = ParagraphStyle("Heading2x", parent=styles["Heading2"], textColor=colors.HexColor("#0f766e"), spaceBefore=10)
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=body, fontSize=8, textColor=colors.HexColor("#475569"))
    story = [
        Paragraph(company_name, brand),
        Paragraph(f"Backed by {company_parent}", body),
        Paragraph(f"{company_contact} · {company_website}", small),
        Spacer(1, 8),
        Paragraph("Quotation", heading),
    ]
    meta = [
        ["Client business", client_name],
        ["Prepared on", prepared_on.isoformat()],
        ["Valid until", valid_until.isoformat()],
        ["Recommended package", quote.package_name],
        ["Budget fit", quote.budget_fit],
        ["Estimated delivery", f"{quote.delivery_days} days after advance and content handover"],
    ]
    table = Table(meta, colWidths=[55 * mm, 110 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0fdfa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [table, Paragraph("Project scope", heading)]
    features = ", ".join(FEATURES.get(feature, feature) for feature in scope.features) or "Core website build"
    story += [
        Paragraph(f"<b>{WEBSITE_TYPES.get(scope.website_type, scope.website_type)}</b> with {scope.pages} page(s).", body),
        Paragraph(features, body),
        Paragraph("Recommended quotation", heading),
        Paragraph(f"<b>{_inr(quote.min_price)} - {_inr(quote.max_price)}</b> (before applicable taxes)", body),
    ]
    rows = [["Item", "Amount"]] + [
        [str(item["label"]), _inr(item["amount"])] for item in quote.line_items
    ]
    if quote.maintenance_total:
        rows.append([f"Maintenance ({quote.maintenance_total // max(1, quote.maintenance_monthly)} month(s))", _inr(quote.maintenance_total)])
    if not quote.hosting_domain:
        rows.append(["Hosting and domain", "Excluded (quoted separately)"])
    price_table = Table(rows, colWidths=[120 * mm, 45 * mm])
    price_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0fdfa")),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story += [price_table, Paragraph("Why this recommendation", heading)]
    story.append(ListFlowable(
        [ListItem(Paragraph(reason, body), leftIndent=10) for reason in quote.reasons],
        bulletType="bullet", start="circle",
    ))
    story.append(Paragraph(
        "Business-size evidence is used only as context. The scope above determines the price. "
        "This is not a claim about the client's revenue.", small,
    ))
    story += [Paragraph("Payment milestones", heading)]
    story.append(ListFlowable(
        [ListItem(Paragraph(f"{item.get('label', '')} - {item.get('percent', 0)}%", body)) for item in catalogue.payment_milestones],
        bulletType="bullet", start="circle",
    ))
    story += [Paragraph("Assumptions", heading)]
    story.append(ListFlowable([ListItem(Paragraph(item, body)) for item in quote.assumptions], bulletType="bullet", start="circle"))
    story += [Paragraph("Exclusions", heading)]
    story.append(ListFlowable([ListItem(Paragraph(item, body)) for item in quote.exclusions], bulletType="bullet", start="circle"))
    story += [
        Paragraph("Next step", heading),
        Paragraph(
            f"Confirm the scope, share brand assets and content, and approve this quotation to schedule the project. "
            f"This quotation is valid until {valid_until.isoformat()}.", body,
        ),
        Spacer(1, 10),
        Paragraph(
            f"{company_name}, backed by {company_parent}. Prices in {catalogue.currency}. "
            "Generated by the MindSmiths Sales Intelligence Platform. No customer-specific discount is applied "
            "unless configured by the sales team.", small,
        ),
    ]
    doc.build(story)
    return buffer.getvalue()


def quote_summary(quote: QuoteRecommendation) -> str:
    return (
        f"{quote.package_name}: {_inr(quote.min_price)}–{_inr(quote.max_price)}, "
        f"{quote.delivery_days} days, effort {quote.effort}, budget fit {quote.budget_fit}"
    )
