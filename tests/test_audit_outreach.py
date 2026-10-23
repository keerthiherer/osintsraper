from config import Settings, WEBSITE_REACHABLE, WEBSITE_UNREACHABLE
from mindsmiths.audit import audit_website
from mindsmiths.opportunity import score_opportunity
from mindsmiths.outreach import generate_outreach
from mindsmiths.website import WebsiteCheck

GOOD_HTML = """<!doctype html>
<html><head>
<title>Anna Interiors</title>
<meta name="description" content="Interior design services in Chennai.">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body>
<h1>Anna Interiors</h1>
<p>We design homes and offices across Chennai. Contact us to book a consultation
with our team. Our studio answers enquiries within one working day and provides a
clear scope before any work starts.</p>
<a href="mailto:hello@annainteriors.in">Email us</a>
<a href="tel:+919876543210">Call us</a>
<a href="/contact">Contact us</a>
<form action="/enquiry"><input name="message"></form>
</body></html>"""


def test_audit_without_url_is_unknown_not_a_negative_claim():
    audit = audit_website(None, settings=Settings())
    assert audit.status == "No website listed"
    assert audit.findings
    assert any("not proof" in item for item in audit.limitations)
    assert audit.recommendations


def test_reachable_audit_reports_checks_and_limits(monkeypatch):
    def fake_check(url, **kwargs):
        return WebsiteCheck(
            status=WEBSITE_REACHABLE,
            url=url,
            http_status=200,
            final_url=url,
            title="Anna Interiors",
            meta_description="Interior design services",
            has_viewport=True,
            https=True,
            html=GOOD_HTML,
            page_text_length=400,
            response_time_ms=400,
            page_size_bytes=1000,
            has_cta=True,
            has_contact_details=True,
            has_enquiry_form=True,
            has_booking_hint=True,
        )

    monkeypatch.setattr("mindsmiths.audit.check_website", fake_check)
    audit = audit_website("https://annainteriors.in", settings=Settings())
    assert audit.status == WEBSITE_REACHABLE
    assert audit.response_time_ms == 400
    assert audit.has_booking is True
    assert audit.has_enquiry is True
    assert audit.checks
    assert any(check.name == "HTTPS" for check in audit.checks)
    assert any("not a full crawl" in item for item in audit.limitations)
    assert audit.summary
    assert audit.services


def test_unreachable_audit_is_treated_as_unconfirmed(monkeypatch):
    def fake_check(url, **kwargs):
        return WebsiteCheck(
            status=WEBSITE_UNREACHABLE,
            url=url,
            error="Connection failed or timed out",
            page_text_length=0,
        )

    monkeypatch.setattr("mindsmiths.audit.check_website", fake_check)
    audit = audit_website("https://missing.invalid", settings=Settings())
    assert audit.status == WEBSITE_UNREACHABLE
    assert audit.error == "Connection failed or timed out"
    assert any("Connection failed" in finding for finding in audit.findings)
    assert "may be temporary" in audit.summary
    assert any("not reachable" in item for item in audit.limitations)
    assert audit.recommendations


def test_outreach_never_claims_unverified_absence():
    record = {"name": "Anna Interiors", "website": "", "website_status": "No website listed"}
    opportunity = score_opportunity(record)
    draft = generate_outreach(record, opportunity, channel="Instagram DM")
    assert "could not find a website listed" in draft.body
    assert "not independently verified" in draft.body
    assert "MindSmiths" in draft.body
    assert "Melouz Technologies" in draft.body
    assert draft.subject == ""


def test_outreach_uses_our_own_website_check_as_observation():
    record = {
        "name": "Anna Interiors",
        "website": "https://annainteriors.in",
        "website_status": "Website unreachable",
    }
    opportunity = score_opportunity(record)
    draft = generate_outreach(
        record,
        opportunity,
        channel="Email",
        tone="Consultative",
        offer="Website redesign",
    )
    assert "did not get a successful response" in draft.body
    assert "not independently verified" not in draft.body
    assert draft.subject == "Website redesign for Anna Interiors"
    assert "15-minute call" in draft.body


def test_outreach_handles_a_missing_name_without_printing_none():
    record = {"name": None, "website": "", "website_status": "Unknown"}
    opportunity = score_opportunity(record)
    draft = generate_outreach(record, opportunity, channel="Email")
    assert "None" not in draft.body
    assert "None" not in draft.subject
    assert "your business" in draft.body
