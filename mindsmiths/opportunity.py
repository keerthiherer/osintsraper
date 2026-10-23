"""Transparent 0-100 website purchase opportunity scoring.

The score estimates the strength of a business's NEED for a better website.
It is not a claim about willingness or intent to buy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from config import (
    OPPORTUNITY_CLASSES,
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
    WEBSITE_CHECK_FAILED,
    OpportunityRules,
)
from .models import now_iso
from .revenue import RevenueAssessment, assess_revenue


@dataclass
class Signal:
    name: str
    points: int
    state: str  # positive | known | unknown
    evidence: str


@dataclass
class OpportunityResult:
    score: int
    classification: str
    confidence: str
    budget_fit: str
    signals: list[Signal] = field(default_factory=list)
    why: str = ""
    objections: list[str] = field(default_factory=list)
    recommended_offer: str = ""
    next_action: str = ""
    unknown: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signals"] = [asdict(signal) for signal in self.signals]
        return data


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _socials(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (record.get("socials") or []) if isinstance(item, dict)]


def _has_recent_activity(record: dict[str, Any], rules: OpportunityRules, today: date) -> bool | None:
    socials = _socials(record)
    if not socials:
        return None
    checked = False
    cutoff = today - timedelta(days=rules.active_days)
    for social in socials:
        if not social.get("activity_verified"):
            continue
        checked = True
        last_active = _parse_date(social.get("last_active"))
        if last_active and last_active >= cutoff:
            return True
    return False if checked else None


def _has_verified_audience(record: dict[str, Any], rules: OpportunityRules) -> bool | None:
    socials = _socials(record)
    if not socials:
        return None
    checked = False
    for social in socials:
        if social.get("followers") is not None and social.get("followers_verified"):
            checked = True
            if int(social["followers"]) >= rules.min_followers:
                return True
    return False if checked else None


def _scale_signal(record: dict[str, Any], rules: OpportunityRules) -> bool | None:
    locations = record.get("number_of_locations")
    catalogue = record.get("catalogue_size")
    if locations is None and catalogue is None and not (record.get("services_summary") or "").strip():
        return None
    if locations is not None and int(locations) >= rules.locations_threshold:
        return True
    if catalogue is not None and int(catalogue) >= rules.catalogue_threshold:
        return True
    if locations is not None or catalogue is not None:
        return False
    return None


def _promotes_signal(record: dict[str, Any]) -> bool | None:
    values = [record.get("has_booking"), record.get("has_enquiry"), record.get("promotes_services")]
    known = [bool(value) for value in values if value is not None]
    if not known:
        return None
    return any(known)


def _established_signal(record: dict[str, Any], rules: OpportunityRules) -> bool | None:
    if record.get("established_signal") is not None:
        return bool(record.get("established_signal"))
    reviews = record.get("review_count")
    rating = record.get("rating")
    if reviews is None:
        return None
    if int(reviews) >= rules.review_threshold:
        if rating is None or float(rating) >= 4.0:
            return True
    return False


def _confidence(known_positive: int, known_total: int, revenue: RevenueAssessment) -> str:
    if known_positive >= 5 and known_total >= 6 and revenue.confidence != "low":
        return "high"
    if known_positive >= 3 and known_total >= 4:
        return "medium"
    return "low"


def _classification(score: int, confidence: str, rules: OpportunityRules) -> str:
    if score >= rules.high_threshold and confidence != "low":
        return OPPORTUNITY_CLASSES[0]
    if score >= rules.potential_threshold:
        return OPPORTUNITY_CLASSES[1]
    if score < rules.low_threshold and confidence != "low":
        return OPPORTUNITY_CLASSES[3]
    return OPPORTUNITY_CLASSES[2]


def _recommended_offer(record: dict[str, Any], revenue: RevenueAssessment) -> tuple[str, str]:
    status = record.get("website_status") or "Unknown"
    has_website = bool((record.get("website") or "").strip())
    if status == WEBSITE_NO_WEBSITE or not has_website:
        if revenue.affordability == "limited":
            return (
                "Starter business website (3-5 pages) with contact and enquiry",
                "Confirm scope and budget, then offer a fixed-price starter package.",
            )
        if record.get("has_booking") or record.get("has_enquiry"):
            return (
                "Business website with booking/enquiry workflow",
                "Ask which bookings or enquiries they currently handle manually.",
            )
        return (
            "Business website with a clear service catalogue and enquiry form",
            "Run a short requirements call before finalising the quotation.",
        )
    if status in {WEBSITE_UNREACHABLE, WEBSITE_CHECK_FAILED}:
        return (
            "Website recovery and redesign package",
            "Verify the current site ownership and hosting, then propose a recovery plan.",
        )
    if record.get("catalogue_size") and int(record["catalogue_size"]) >= 20:
        return (
            "Catalogue or e-commerce upgrade",
            "Confirm whether online payments and inventory management are required.",
        )
    return (
        "Website redesign, performance and enquiry optimisation",
        "Share the audit findings and ask which improvements matter most.",
    )


def _objections(record: dict[str, Any], revenue: RevenueAssessment) -> list[str]:
    objections = []
    if (record.get("website") or "").strip():
        objections.append("They already have a website; they may prefer incremental fixes over a rebuild.")
    if revenue.affordability == "limited":
        objections.append("Budget may be limited; lead with a smaller starter scope.")
    if revenue.affordability == "unknown":
        objections.append("Budget fit is unknown; ask about scope and budget before quoting.")
    if not (record.get("phone") or record.get("email")):
        objections.append("No verified decision-maker contact yet; outreach channel is uncertain.")
    if (record.get("website_status") or "") == WEBSITE_NO_WEBSITE:
        objections.append("Website absence is based on collected listings and may need independent verification.")
    if not record.get("has_booking") and not record.get("has_enquiry"):
        objections.append("No public booking/enquiry facility was found; confirm whether that is a priority.")
    if not objections:
        objections.append("Purchase timing and decision process are unknown.")
    return objections[:5]


def _why(record: dict[str, Any], signals: list[Signal]) -> str:
    positives = [signal.evidence for signal in signals if signal.state == "positive"]
    if not positives:
        return (
            "There is not enough verified public evidence yet to argue that this business needs "
            "a new website. Collect website, contact and social evidence first."
        )
    lead = " ".join(positives[:4])
    return (
        f"{lead}. These are need indicators, not a statement that the business intends to buy. "
        "Website absence or problems still need independent verification before outreach."
    )


def score_opportunity(
    record: dict[str, Any],
    *,
    rules: OpportunityRules | None = None,
    revenue: RevenueAssessment | None = None,
    today: date | None = None,
) -> OpportunityResult:
    rules = rules or OpportunityRules()
    today = today or datetime.now(timezone.utc).date()
    revenue = revenue or assess_revenue(record, rules=rules)
    signals: list[Signal] = []
    score = 0

    status = record.get("website_status") or "Unknown"
    website = (record.get("website") or "").strip()

    if status == WEBSITE_NO_WEBSITE and not website:
        score += rules.no_website
        signals.append(Signal(
            "No website listed", rules.no_website, "positive",
            "No website is listed in the collected public sources",
        ))
    elif not website and status not in {WEBSITE_NO_WEBSITE}:
        signals.append(Signal(
            "No website listed", 0, "unknown",
            "No website URL was found, but website absence is not independently verified",
        ))

    issues = [part.strip() for part in (record.get("website_issues") or "").split(";") if part.strip()]
    if website and (status in {WEBSITE_UNREACHABLE, WEBSITE_CHECK_FAILED} or issues):
        score += rules.website_problems
        detail = (
            f"Website check found: {', '.join(issues[:3])}"
            if issues else "Website did not respond to an automated check"
        )
        signals.append(Signal("Website usability/functionality problem", rules.website_problems, "positive", detail))
    elif website and status == WEBSITE_REACHABLE:
        signals.append(Signal("Website usability/functionality problem", 0, "known", "Website responded; no major issue recorded"))

    activity = _has_recent_activity(record, rules, today)
    if activity:
        score += rules.recent_activity
        signals.append(Signal("Recent verified activity", rules.recent_activity, "positive", "Recent verified social activity"))
    elif activity is None:
        signals.append(Signal("Recent verified activity", 0, "unknown", "Activity could not be verified"))
    else:
        signals.append(Signal("Recent verified activity", 0, "known", "No recent verified activity found"))

    audience = _has_verified_audience(record, rules)
    if audience:
        score += rules.verified_audience
        signals.append(Signal("Verified social audience", rules.verified_audience, "positive", f"Verified audience of at least {rules.min_followers:,}"))
    elif audience is None:
        signals.append(Signal("Verified social audience", 0, "unknown", "Follower count is unavailable or unverified"))
    else:
        signals.append(Signal("Verified social audience", 0, "known", "Verified audience is below the threshold"))

    scale = _scale_signal(record, rules)
    if scale:
        score += rules.multiple_locations_or_catalogue
        signals.append(Signal("Multiple locations or substantial catalogue", rules.multiple_locations_or_catalogue, "positive", "Multiple locations or a substantial public catalogue"))
    elif scale is None:
        signals.append(Signal("Multiple locations or substantial catalogue", 0, "unknown", "Location count/catalogue size not verified"))
    else:
        signals.append(Signal("Multiple locations or substantial catalogue", 0, "known", "Single location or small catalogue"))

    promotes = _promotes_signal(record)
    if promotes:
        score += rules.promotes_services
        signals.append(Signal("Promotes services/bookings/enquiries", rules.promotes_services, "positive", "Public booking, enquiry or service promotion found"))
    elif promotes is None:
        signals.append(Signal("Promotes services/bookings/enquiries", 0, "unknown", "Booking/enquiry promotion not verified"))
    else:
        signals.append(Signal("Promotes services/bookings/enquiries", 0, "known", "No public booking/enquiry promotion found"))

    if (record.get("phone") or "").strip() or (record.get("email") or "").strip():
        score += rules.contact_available
        signals.append(Signal("Public business contact", rules.contact_available, "positive", "Public phone or business email available"))
    else:
        signals.append(Signal("Public business contact", 0, "unknown", "No public phone/email found; this does not prove one is absent"))

    established = _established_signal(record, rules)
    if established:
        score += rules.established_operations
        signals.append(Signal("Established operations", rules.established_operations, "positive", "Public reviews/rating or user-confirmed operations evidence"))
    elif established is None:
        signals.append(Signal("Established operations", 0, "unknown", "Established operations evidence not collected"))
    else:
        signals.append(Signal("Established operations", 0, "known", "Limited public operations evidence"))

    if record.get("expansion_signal") is True:
        score += rules.expansion
        signals.append(Signal("Public expansion/new branch", rules.expansion, "positive", "User-confirmed public expansion signal"))
    elif record.get("expansion_signal") is None:
        signals.append(Signal("Public expansion/new branch", 0, "unknown", "No expansion signal collected"))
    else:
        signals.append(Signal("Public expansion/new branch", 0, "known", "No public expansion signal recorded"))

    final = max(0, min(100, score))
    known = [signal for signal in signals if signal.state != "unknown"]
    positives = [signal for signal in signals if signal.state == "positive"]
    confidence = _confidence(len(positives), len(known), revenue)
    classification = _classification(final, confidence, rules)
    unknown = [signal.name for signal in signals if signal.state == "unknown"]
    offer, next_action = _recommended_offer(record, revenue)

    return OpportunityResult(
        score=final,
        classification=classification,
        confidence=confidence,
        budget_fit=revenue.affordability,
        signals=signals,
        why=_why(record, signals),
        objections=_objections(record, revenue),
        recommended_offer=offer,
        next_action=next_action,
        unknown=unknown,
    )
