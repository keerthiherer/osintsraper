from io import BytesIO

import pandas as pd

from mindsmiths.export import (
    export_csv,
    export_freelance_csv,
    export_freelance_excel,
    lead_rows,
)


def intelligence_record():
    return {
        "name": "Anna Interiors",
        "city": "Chennai",
        "website_status": "No website listed",
        "opportunity_score": 77,
        "opportunity_class": "High-priority opportunity",
        "opportunity_confidence": "medium",
        "budget_fit": "moderate",
        "revenue_category": "Estimated business-size category only",
        "revenue_band": "Small to medium business",
        "revenue_confidence": "medium",
        "verified_revenue": 5_000_000,
        "third_party_revenue": 2_000_000,
        "follow_up_date": "2026-10-30",
        "quoted_amount": 50_000,
        "proposed_quotation": 45_000,
        "client_budget": 40_000,
        "status": "Quotation sent",
        "socials": [],
    }


def test_lead_export_contains_intelligence_and_crm_fields_without_secrets():
    row = lead_rows([intelligence_record()])[0]
    assert row["Website Opportunity Score"] == 77
    assert row["Revenue Category"] == "Estimated business-size category only"
    assert row["Follow-up Date"] == "2026-10-30"
    assert row["Actual Quoted Amount"] == 50_000
    assert row["Sales Status"] == "Quotation sent"

    text = export_csv([intelligence_record()]).decode("utf-8-sig")
    assert "Website Opportunity Score" in text
    assert "serpapi" not in text.lower()
    assert "upwork_access_token" not in text.lower()


def test_freelance_export_csv_and_excel():
    records = [{
        "title": "WordPress website redesign",
        "platform": "Freelancer.com",
        "url": "https://example.invalid/job/1",
        "project_status": "Open and verified",
        "budget_min": 25_000,
        "budget_max": 40_000,
        "currency": "INR",
        "match_score": 88,
        "score_notes": "Good match",
        "is_new": 1,
        "is_demo": 0,
    }]
    csv_text = export_freelance_csv(records).decode("utf-8-sig")
    assert "WordPress website redesign" in csv_text
    assert "Match Score" in csv_text

    excel = export_freelance_excel(records)
    assert excel[:2] == b"PK"
    frame = pd.read_excel(BytesIO(excel), sheet_name="Freelance")
    assert frame.loc[0, "Title"] == "WordPress website redesign"
    assert frame.loc[0, "Match Score"] == 88
