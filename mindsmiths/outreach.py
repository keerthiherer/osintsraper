"""Evidence-based outreach drafts. Nothing is sent automatically."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .opportunity import OpportunityResult

CHANNELS = ["Instagram DM", "WhatsApp business message", "Email", "LinkedIn message"]
TONES = ["Professional", "Friendly", "Concise", "Consultative"]
OFFERS = [
    "Business website",
    "Website redesign",
    "Booking / enquiry workflow",
    "E-commerce or catalogue",
    "Website care and SEO",
]


@dataclass
class OutreachDraft:
    channel: str
    subject: str
    body: str
    observation: str
    tone: str
    offer: str


def _observation(record: dict[str, Any]) -> tuple[str, bool]:
    """Return a genuine observation and whether it came from our own check."""
    business_name = record.get("name") or "your business"
    website = (record.get("website") or "").strip()
    status = record.get("website_status") or "Unknown"
    if status == "No website listed" and not website:
        return (
            f"I could not find a website listed for {business_name} in public listings",
            False,
        )
    if website and status in {"Website unreachable", "Website check failed"}:
        return (
            f"our automated check of {website} did not get a successful response",
            True,
        )
    if website and status == "Website reachable":
        issues = (record.get("website_issues") or "").strip()
        if issues:
            return (
                f"our lightweight automated check of {website} noted {issues.split(';')[0].strip()}",
                True,
            )
        if not record.get("has_enquiry") and not record.get("has_cta"):
            return (
                f"your website {website} is reachable, but I could not see an obvious enquiry action on the homepage",
                True,
            )
        return (f"I had a quick look at {website} and the business information was clear", True)
    category = record.get("category") or "local"
    city = record.get("city") or "your area"
    return (
        f"I came across {business_name} while researching {category} businesses in {city}",
        False,
    )


def _benefit(offer: str) -> str:
    benefits = {
        "Business website": "a clear business website can turn searches and social visits into enquiries",
        "Website redesign": "a focused redesign can make it easier for customers to understand your services and contact you",
        "Booking / enquiry workflow": "a simple booking or enquiry flow can reduce back-and-forth messages and missed requests",
        "E-commerce or catalogue": "an online catalogue can help customers browse and ask about products without messaging first",
        "Website care and SEO": "regular care and basic SEO can keep the site fast, current and easier to find",
    }
    return benefits.get(offer, benefits["Business website"])


def _next_step(channel: str) -> str:
    if channel == "Email":
        return "Would a short 15-minute call next week be useful?"
    if channel == "WhatsApp business message":
        return "If useful, I can send a one-page outline with a rough scope and price range."
    if channel == "LinkedIn message":
        return "Would you be open to a brief conversation about it?"
    return "If this is relevant, I can share a short outline here. If not, no problem at all."


def generate_outreach(
    record: dict[str, Any],
    opportunity: OpportunityResult,
    *,
    channel: str = "Instagram DM",
    tone: str = "Professional",
    offer: str = "Business website",
) -> OutreachDraft:
    observation, checked = _observation(record)
    name = record.get("name") or "there"
    greeting = {
        "Instagram DM": f"Hi {name} team,",
        "WhatsApp business message": f"Hello {name} team,",
        "Email": f"Hello {name} team,",
        "LinkedIn message": f"Hi {name} team,",
    }.get(channel, f"Hi {name} team,")
    benefit = _benefit(offer)
    caveat = ""
    if not checked:
        caveat = " I have not independently verified your website situation, so please correct me if I am wrong."
    if tone == "Friendly":
        opening = f"I hope you are doing well. {observation.capitalize()}."
    elif tone == "Concise":
        opening = f"{observation.capitalize()}."
    elif tone == "Consultative":
        opening = f"{observation.capitalize()}. I work with businesses on practical website and enquiry improvements."
    else:
        opening = f"{observation.capitalize()}. I am reaching out from MindSmiths, backed by Melouz Technologies."

    closing = _next_step(channel)
    body = (
        f"{greeting}\n\n{opening}{caveat} We help businesses with {offer.lower()}; "
        f"{benefit}. {closing}\n\nRegards,\nMindSmiths\nBacked by Melouz Technologies Pvt Ltd"
    )
    if tone == "Concise":
        body = (
            f"{greeting}\n\n{opening}{caveat} {benefit.capitalize()}. {closing}\n\n"
            "MindSmiths (Melouz Technologies)"
        )

    subject = f"{offer} for {record.get('name') or 'your business'}"
    if channel == "Instagram DM":
        subject = ""
    if channel == "LinkedIn message" and len(body) > 900:
        body = body[:900].rsplit(" ", 1)[0] + "…"
    return OutreachDraft(
        channel=channel,
        subject=subject,
        body=body.strip(),
        observation=observation,
        tone=tone,
        offer=offer,
    )
