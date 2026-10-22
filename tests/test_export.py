from io import BytesIO

import pandas as pd

from mindsmiths.export import export_csv, export_excel, lead_rows


def sample_records():
    return [{
        "id": 1,
        "name": "Anna Nagar Lens Studio",
        "category": "Photography studio",
        "address": "2nd Avenue, Anna Nagar",
        "city": "Chennai",
        "locality": "Anna Nagar",
        "phone": "+91 90000 10001",
        "email": "hello@annalens.in",
        "website": "",
        "website_status": "No website listed",
        "website_http_status": None,
        "website_issues": "",
        "rating": 4.8,
        "review_count": 143,
        "contact_page": "",
        "form_url": "",
        "listing_url": "https://www.google.com/maps/search/?api=1&query=test",
        "opening_hours": "Mon-Sat",
        "score": 95,
        "priority": "High priority",
        "qualification_notes": "No website listed (+30)",
        "status": "new",
        "notes": "Call after 10am",
        "source": "demo",
        "collected_at": "2026-10-01",
        "socials": [
            {"platform": "instagram", "url": "https://www.instagram.com/teststudio/",
             "followers": 12500, "followers_verified": True,
             "last_active": "2026-10-18", "activity_verified": True},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/teststudio/",
             "followers": 300, "followers_verified": False,
             "last_active": None, "activity_verified": False},
        ],
    }]


def test_lead_rows_flatten_socials_and_unknowns():
    rows = lead_rows(sample_records())
    row = rows[0]
    assert row["Business Name"] == "Anna Nagar Lens Studio"
    assert row["Instagram Followers"] == "12500"
    assert row["LinkedIn Followers"] == "~300 (Needs manual verification)"
    assert row["Facebook URL"] == ""
    assert row["Lead Score"] == 95


def test_csv_export():
    data = export_csv(sample_records())
    text = data.decode("utf-8-sig")
    assert "Business Name" in text
    assert "Anna Nagar Lens Studio" in text
    assert "Needs manual verification" in text
    assert "api_key" not in text.lower()


def test_excel_export_is_readable_and_has_no_secrets():
    data = export_excel(sample_records())
    assert data[:2] == b"PK"
    frame = pd.read_excel(BytesIO(data), sheet_name="Leads")
    assert frame.loc[0, "Business Name"] == "Anna Nagar Lens Studio"
    assert str(frame.loc[0, "Lead Score"]) == "95"
    assert not any("api" in str(column).lower() and "key" in str(column).lower() for column in frame.columns)

