"""Revenue intelligence and broad affordability bands.

This module never invents revenue. It separates:

1. revenue explicitly disclosed by the business;
2. a cited third-party estimate entered by the user;
3. a broad business-size band inferred from public signals;
4. insufficient evidence.

Review counts are never multiplied by an invented average purchase value.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import (
    REVENUE_CATEGORIES,
    OpportunityRules,
)

REVENUE_CONFIDENCE = ("low", "medium", "high")


@dataclass
class RevenueAssessment:
    category: str
    band: str
    confidence: str
    affordability: str
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    estimated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    warning: str = ""
    revenue_range: tuple[float, float] | None = None
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.revenue_range is not None:
            data["revenue_range"] = list(self.revenue_range)
        return data


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _affordability_from_revenue(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 1_500_000:
        return "limited"
    if value < 10_000_000:
        return "moderate"
    return "higher-capability"


def _sources(record: dict[str, Any], evidence_records: list[dict[str, Any]] | None = None) -> list[str]:
    urls = []
    for key in ("listing_url", "website", "contact_page"):
        value = (record.get(key) or "").strip()
        if value and value not in urls:
            urls.append(value)
    for item in evidence_records or []:
        url = (item.get("source_url") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls[:12]


def _size_points(record: dict[str, Any], rules: OpportunityRules) -> tuple[int, list[str], int]:
    points = 0
    evidence: list[str] = []
    known = 0

    locations = _num(record.get("number_of_locations"))
    if locations is not None:
        known += 1
        if locations >= 5:
            points += 4
            evidence.append(f"{int(locations)} public locations")
        elif locations >= 2:
            points += 2
            evidence.append(f"{int(locations)} public locations")
        else:
            points += 1
            evidence.append("One public location")

    catalogue = _num(record.get("catalogue_size"))
    if catalogue is not None:
        known += 1
        if catalogue >= 100:
            points += 3
            evidence.append(f"Large public catalogue ({int(catalogue)} items)")
        elif catalogue >= rules.catalogue_threshold:
            points += 2
            evidence.append(f"Public catalogue with {int(catalogue)} items")
        elif catalogue > 0:
            points += 1
            evidence.append(f"Public catalogue with {int(catalogue)} items")

    price_max = _num(record.get("product_price_max"))
    price_min = _num(record.get("product_price_min"))
    if price_max is not None:
        known += 1
        if price_max >= 100_000:
            points += 3
        elif price_max >= 20_000:
            points += 2
        else:
            points += 1
        if price_min is not None:
            evidence.append(f"Public price range ₹{price_min:,.0f}–₹{price_max:,.0f}")
        else:
            evidence.append(f"Public prices up to ₹{price_max:,.0f}")

    reviews = _num(record.get("review_count"))
    rating = _num(record.get("rating"))
    if reviews is not None:
        known += 1
        if reviews >= 300:
            points += 3
            evidence.append(f"{int(reviews)} public reviews")
        elif reviews >= 80:
            points += 2
            evidence.append(f"{int(reviews)} public reviews")
        elif reviews >= 20:
            points += 1
            evidence.append(f"{int(reviews)} public reviews")
        elif reviews > 0:
            evidence.append(f"{int(reviews)} public reviews (limited scale signal)")
        if rating is not None and rating >= 4.2 and reviews >= 20:
            points += 1
            evidence.append(f"Strong public rating ({rating:.1f})")

    services = (record.get("services_summary") or "").strip()
    if services:
        known += 1
        points += 1
        evidence.append("Publicly listed services/prices")

    if record.get("has_booking") or record.get("has_enquiry") or record.get("promotes_services"):
        known += 1
        points += 1
        evidence.append("Public booking/enquiry or service promotion")

    if record.get("established_signal"):
        known += 1
        points += 2
        evidence.append("User-confirmed evidence of established operations")

    if record.get("expansion_signal"):
        known += 1
        points += 1
        evidence.append("Publicly announced expansion/new branch")

    category = (record.get("category") or "").lower()
    if any(word in category for word in (
        "interior", "architect", "event", "wedding", "clinic", "consult", "agency", "jewel",
    )):
        points += 1
        evidence.append("Higher-ticket business category")

    return points, evidence, known


def assess_revenue(
    record: dict[str, Any],
    *,
    rules: OpportunityRules | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
) -> RevenueAssessment:
    """Return a conservative revenue/business-size assessment."""
    rules = rules or OpportunityRules()
    sources = _sources(record, evidence_records)

    verified = _num(record.get("verified_revenue"))
    if verified is not None and verified > 0:
        source = (record.get("verified_revenue_source") or "").strip()
        if not source:
            return RevenueAssessment(
                category=REVENUE_CATEGORIES[3],
                band="Unknown",
                confidence="low",
                affordability="unknown",
                evidence=["A revenue figure was entered without a cited source, so it was not used."],
                sources=sources,
                warning=(
                    "Verified revenue requires a public disclosure or source note. "
                    "Add the source and recompute before treating this figure as fact."
                ),
                method="Uncited revenue claim rejected.",
            )
        return RevenueAssessment(
            category=REVENUE_CATEGORIES[0],
            band="Verified revenue disclosed",
            confidence="high",
            affordability=_affordability_from_revenue(verified),
            evidence=[f"Publicly disclosed revenue: ₹{verified:,.0f} INR"],
            sources=[source] if source else sources,
            warning="Only the disclosed figure is treated as fact; no additional revenue is inferred.",
            revenue_range=(verified, verified),
            method="Public revenue disclosure entered by the user.",
        )

    third_party = _num(record.get("third_party_revenue"))
    if third_party is not None and third_party > 0:
        source = (record.get("third_party_revenue_source") or "").strip()
        if not source:
            return RevenueAssessment(
                category=REVENUE_CATEGORIES[3],
                band="Unknown",
                confidence="low",
                affordability="unknown",
                evidence=["A third-party revenue estimate was entered without a citation, so it was not used."],
                sources=sources,
                warning=(
                    "Third-party estimates must keep their source attached. "
                    "Add the source and recompute before relying on this figure."
                ),
                method="Uncited third-party estimate rejected.",
            )
        return RevenueAssessment(
            category=REVENUE_CATEGORIES[1],
            band="Third-party estimate",
            confidence="medium",
            affordability=_affordability_from_revenue(third_party),
            evidence=[f"Third-party revenue estimate: ₹{third_party:,.0f} INR"],
            sources=[source] if source else sources,
            warning=(
                "This is a third-party estimate, not a verified disclosure. "
                "Keep the cited source attached and do not present it as fact."
            ),
            revenue_range=(third_party, third_party),
            method="Cited third-party estimate entered by the user.",
        )

    points, evidence, known = _size_points(record, rules)
    if known == 0 or points == 0:
        return RevenueAssessment(
            category=REVENUE_CATEGORIES[3],
            band="Unknown",
            confidence="low",
            affordability="unknown",
            evidence=["No reliable public business-size signals were collected."],
            sources=sources,
            warning=(
                "Insufficient evidence to estimate business size or affordability. "
                "Use a standard scope-based quotation and ask the client about requirements."
            ),
            method="No defensible revenue estimate.",
        )

    if points >= 8:
        band = "Larger / multi-location"
        affordability = "higher-capability"
    elif points >= 5:
        band = "Small to medium business"
        affordability = "moderate"
    elif points >= 2:
        band = "Small business"
        affordability = "limited"
    else:
        band = "Micro business or limited public evidence"
        affordability = "limited"

    if known >= 4 and points >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return RevenueAssessment(
        category=REVENUE_CATEGORIES[2],
        band=band,
        confidence=confidence,
        affordability=affordability,
        evidence=evidence,
        sources=sources,
        warning=(
            "This is a broad business-size/affordability band, not a revenue figure. "
            "Do not quote it as revenue. Review counts are used only as a scale signal, "
            "never multiplied by an invented purchase value."
        ),
        method="Transparent size-band heuristics based on public signals.",
    )


def assessment_json(assessment: RevenueAssessment) -> str:
    import json

    return json.dumps(assessment.to_dict(), ensure_ascii=False, default=str)
