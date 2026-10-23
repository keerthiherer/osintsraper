"""Lightweight, evidence-based website audit and upsell opportunities."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from config import (
    Settings,
    WEBSITE_CHECK_FAILED,
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
)
from .contacts import extract_contacts
from .models import normalize_url
from .website import WebsiteCheck, check_website


@dataclass
class AuditCheck:
    name: str
    state: str  # pass | issue | unknown
    detail: str
    evidence: str = ""


@dataclass
class WebsiteAudit:
    status: str
    url: str
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    checks: list[AuditCheck] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    response_time_ms: int | None = None
    page_size_bytes: int | None = None
    has_booking: bool | None = None
    has_enquiry: bool | None = None
    has_cta: bool | None = None
    has_contact_details: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [asdict(check) for check in self.checks]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _add(checks: list[AuditCheck], name: str, state: str, detail: str, evidence: str = "") -> None:
    checks.append(AuditCheck(name=name, state=state, detail=detail, evidence=evidence))


def audit_website(
    url: str | None,
    *,
    settings: Settings,
    session=None,
    contact_page: str = "",
) -> WebsiteAudit:
    raw = (url or "").strip()
    if not raw:
        audit = WebsiteAudit(
            status=WEBSITE_NO_WEBSITE,
            url="",
            findings=["No website URL was found in the collected public sources."],
            limitations=["Website absence is not proof that the business has no website; verify independently."],
            recommendations=[
                "Confirm whether a website or social-only presence exists.",
                "If no website exists, propose a small business site with contact, services and enquiry.",
            ],
            services=["Business website", "Landing page", "Booking/enquiry setup"],
            summary="No website URL was available for a live audit. This is an unknown state, not a negative finding about the business.",
        )
        return audit

    check: WebsiteCheck = check_website(
        raw,
        timeout=settings.request_timeout,
        session=session,
        user_agent=settings.user_agent,
    )
    audit = WebsiteAudit(
        status=check.status,
        url=normalize_url(check.final_url or raw),
        error=check.error,
        response_time_ms=check.response_time_ms,
        page_size_bytes=check.page_size_bytes,
        has_cta=check.has_cta,
        has_contact_details=check.has_contact_details,
        has_enquiry=check.has_enquiry_form,
        has_booking=check.has_booking_hint,
    )
    checks: list[AuditCheck] = []

    if check.status == WEBSITE_REACHABLE:
        _add(checks, "Homepage response", "pass", f"HTTP {check.http_status}", raw)
        _add(checks, "HTTPS", "pass" if check.https else "issue",
             "HTTPS is used" if check.https else "The final page is served over HTTP")
        _add(checks, "Page title", "pass" if check.title else "issue",
             "Title found" if check.title else "No page title found", check.title)
        _add(checks, "Meta description", "pass" if check.meta_description else "issue",
             "Meta description found" if check.meta_description else "No meta description found",
             check.meta_description)
        _add(checks, "Mobile viewport", "pass" if check.has_viewport else "issue",
             "Mobile viewport metadata found" if check.has_viewport else "No mobile viewport metadata found")
        _add(checks, "Visible chat/contact call to action", "pass" if check.has_cta else "issue",
             "A contact/booking/buy call to action was found" if check.has_cta else "No obvious call to action was found")
        _add(checks, "Visible business contact details", "pass" if check.has_contact_details else "issue",
             "A phone, email or contact link was found" if check.has_contact_details else "No visible phone/email was found on the homepage")
        _add(checks, "Enquiry form", "pass" if check.has_enquiry_form else "unknown",
             "A form was found" if check.has_enquiry_form else "No form found on the homepage (may exist on another page)")
        _add(checks, "Booking/appointment hint", "pass" if check.has_booking_hint else "unknown",
             "Booking/appointment wording was found" if check.has_booking_hint else "No booking wording found on the homepage")

        if check.page_text_length < 200:
            _add(checks, "Homepage content", "issue", "Very little visible text was found on the homepage")
        else:
            _add(checks, "Homepage content", "pass", f"About {check.page_text_length} characters of visible text")

        if check.response_time_ms is not None:
            if check.response_time_ms > 3000:
                _add(checks, "Homepage response time", "issue", f"{check.response_time_ms} ms", "server response")
            elif check.response_time_ms > 1500:
                _add(checks, "Homepage response time", "unknown", f"{check.response_time_ms} ms (moderate)", "server response")
            else:
                _add(checks, "Homepage response time", "pass", f"{check.response_time_ms} ms")
        if check.page_size_bytes is not None:
            if check.page_size_bytes > 1_500_000:
                _add(checks, "Homepage transfer size", "issue", f"{check.page_size_bytes / 1_000_000:.1f} MB")
            else:
                _add(checks, "Homepage transfer size", "pass", f"{check.page_size_bytes / 1000:.0f} KB")

        details = extract_contacts(check.html, check.final_url or raw)
        target_contact = normalize_url(contact_page or details.contact_page)
        if target_contact and target_contact != audit.url:
            contact_check = check_website(
                target_contact,
                timeout=settings.request_timeout,
                session=session,
                user_agent=settings.user_agent,
            )
            if contact_check.status == WEBSITE_REACHABLE:
                _add(checks, "Contact page", "pass", f"Contact page responded (HTTP {contact_check.http_status})", target_contact)
            else:
                _add(checks, "Contact page", "issue", f"Contact page check returned {contact_check.status}", target_contact)
        elif target_contact:
            _add(checks, "Contact page", "pass", "The homepage is the contact page", target_contact)
        else:
            _add(checks, "Contact page", "unknown", "No contact page link was found on the homepage")

        if not details.emails:
            _add(checks, "Email on homepage", "unknown", "No email was found on the homepage; it may be on a contact page")
        if not details.phones:
            _add(checks, "Phone on homepage", "unknown", "No phone was found on the homepage; it may be on a contact page")

        audit.has_booking = bool(check.has_booking_hint)
        audit.has_enquiry = bool(check.has_enquiry_form or details.form_url)
        audit.has_cta = bool(check.has_cta)
        audit.has_contact_details = bool(check.has_contact_details or details.emails or details.phones)

    elif check.status == WEBSITE_UNREACHABLE:
        _add(checks, "Homepage response", "issue", check.error or "The homepage did not respond", raw)
    else:
        _add(checks, "Homepage response", "unknown", check.error or "The website could not be checked", raw)

    audit.checks = checks
    issues = [check for check in checks if check.state == "issue"]
    audit.findings = [f"{check.name}: {check.detail}" for check in issues]

    audit.limitations = [
        "Only the homepage and one contact page were checked; this is not a full crawl.",
        "Performance is a single server-response and page-size observation, not a full Core Web Vitals test.",
        "Missing metadata alone does not mean a website is bad or that the business needs a rebuild.",
    ]
    if check.status != WEBSITE_REACHABLE:
        audit.limitations.append("The site was not reachable, so page-level checks could not be completed.")

    if check.status == WEBSITE_REACHABLE:
        if not check.https:
            audit.recommendations.append("Enable HTTPS and redirect HTTP traffic to the secure version.")
        if not check.has_viewport:
            audit.recommendations.append("Add responsive mobile layout and viewport metadata.")
        if not check.has_cta or not check.has_contact_details:
            audit.recommendations.append("Make the primary contact/enquiry action clearer on the homepage.")
        if not check.has_enquiry_form:
            audit.recommendations.append("Add a short enquiry form or a clear link to an existing contact workflow.")
        if check.response_time_ms and check.response_time_ms > 3000:
            audit.recommendations.append("Investigate slow server response and page weight.")
        if check.title and check.meta_description:
            audit.recommendations.append("Keep metadata current; no urgent metadata rebuild is indicated.")
        if not audit.recommendations:
            audit.recommendations.append("No major issue was found in this lightweight check; focus on content and conversion improvements.")
        audit.services = [
            "Website redesign and conversion improvements",
            "Enquiry/booking workflow",
            "Performance and hosting review",
            "SEO and content update",
        ]
        audit.summary = (
            f"Automated check of {audit.url} found {len(issues)} issue(s). "
            "This is a limited homepage check, not a full website audit and not a judgement of the business."
        )
    elif check.status == WEBSITE_UNREACHABLE:
        audit.recommendations.append("Verify domain/hosting ownership, then propose a recovery or rebuild plan.")
        audit.services = ["Website recovery", "Redesign", "Hosting migration"]
        audit.summary = (
            f"The website {audit.url} did not respond when checked ({check.error or 'unreachable'}). "
            "This may be temporary; retry before making a sales claim."
        )
    else:
        audit.recommendations.append("Retry the check later; the failure may be temporary or caused by anti-bot protection.")
        audit.services = ["Website review"]
        audit.summary = "The website could not be checked in this run. Treat the result as unknown, not as proof of a problem."

    return audit
