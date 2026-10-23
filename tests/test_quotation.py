from datetime import date

from config import REVENUE_CATEGORIES
from mindsmiths.pricing import PricingCatalogue, default_catalogue, load_catalogue, save_catalogue
from mindsmiths.quotation import (
    QuoteScope,
    build_quote_html,
    build_quote_pdf,
    default_scope,
    recommend_quote,
)
from mindsmiths.revenue import RevenueAssessment


def revenue(affordability="unknown"):
    return RevenueAssessment(
        category=REVENUE_CATEGORIES[2] if affordability != "unknown" else REVENUE_CATEGORIES[3],
        band="Small business" if affordability != "unknown" else "Unknown",
        confidence="low",
        affordability=affordability,
    )


def catalogue():
    return PricingCatalogue(
        minimum_project_price=10_000,
        maximum_project_price=200_000,
        included_pages=5,
        per_extra_page=1_000,
        maintenance_monthly=2_000,
        hosting_domain_annual=6_000,
        base_prices={"landing": 12_000, "business": 40_000},
        feature_prices={
            "booking_enquiry": 5_000,
            "cms_admin": 8_000,
            "content_page": 2_000,
            "custom_integration": 10_000,
            "seo_setup": 5_000,
            "additional_support": 3_000,
        },
    )


def test_quote_uses_scope_not_assumed_revenue():
    scope = QuoteScope(
        website_type="business",
        pages=8,
        features=["booking_enquiry", "cms_admin"],
        maintenance_months=3,
        include_hosting_domain=True,
    )
    quote = recommend_quote(
        {"name": "Client", "website_status": ""},
        revenue("higher-capability"),
        scope,
        catalogue(),
    )
    assert quote.package_name == "Business Website Package"
    assert quote.min_price == 57_500
    assert quote.max_price == 68_700
    assert quote.delivery_days == 28
    assert quote.maintenance_total == 6_000
    assert quote.hosting_domain == 6_000
    assert any(item["label"] == "Hosting and domain (annual)" for item in quote.line_items)
    assert any("not on assumed revenue" in reason for reason in quote.reasons)


def test_quote_is_clamped_by_catalogue_limits():
    quote = recommend_quote(
        {"name": "Client"},
        revenue(),
        QuoteScope(website_type="ecommerce", pages=100, features=list(catalogue().feature_prices)),
        catalogue(),
    )
    assert quote.min_price >= 10_000
    assert quote.max_price <= 200_000
    assert quote.min_price <= quote.max_price


def test_default_scope_respects_evidence_and_budget():
    limited = default_scope(
        {"website_status": "No website listed", "catalogue_size": None},
        revenue("limited"),
    )
    ecommerce = default_scope(
        {"website_status": "Website reachable", "catalogue_size": 30},
        revenue("moderate"),
    )
    assert limited.website_type == "landing"
    assert ecommerce.website_type == "ecommerce"
    assert "cms_admin" in ecommerce.features


def test_html_quote_escapes_client_and_includes_price():
    scope = QuoteScope(website_type="business", pages=5, features=["booking_enquiry"])
    quote = recommend_quote({"name": "Client"}, revenue(), scope, catalogue())
    html = build_quote_html(
        "<Anna & Co>",
        scope,
        quote,
        catalogue(),
        prepared_on=date(2026, 10, 23),
    )
    assert "<title>Quotation — &lt;Anna &amp; Co&gt;</title>" in html
    assert "&lt;Anna &amp; Co&gt;" in html
    assert "INR" in html
    assert "2026-11-22" in html
    assert "MindSmiths" in html
    assert "Melouz Technologies" in html


def test_pdf_quote_is_generated():
    scope = QuoteScope(website_type="business", pages=5, maintenance_months=1)
    quote = recommend_quote({"name": "Client"}, revenue(), scope, catalogue())
    pdf = build_quote_pdf("Client", scope, quote, catalogue(), prepared_on=date(2026, 10, 23))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_catalogue_roundtrip_and_fallback(tmp_path):
    path = tmp_path / "catalogue.json"
    save_catalogue(path, catalogue())
    loaded = load_catalogue(path)
    assert loaded.base_prices["business"] == 40_000
    assert loaded.maintenance_monthly == 2_000

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    default = default_catalogue()
    fallback = load_catalogue(broken)
    assert fallback.base_prices == default.base_prices
