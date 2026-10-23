"""Configurable 0-100 scoring for freelance opportunities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from config import FreelanceRules

CAPABILITY_TERMS = {
    "website", "web development", "web design", "landing page", "wordpress", "shopify",
    "e-commerce", "ecommerce", "react", "next.js", "nextjs", "django", "flask", "frontend",
    "front-end", "backend", "back-end", "full stack", "full-stack", "redesign",
    "website maintenance", "performance", "seo", "webflow", "php", "javascript", "api",
}


@dataclass
class FreelanceScore:
    score: int
    notes: list[str] = field(default_factory=list)
    effort: str = "Unknown"

    def explanation(self) -> str:
        return "; ".join(self.notes)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def score_freelance(
    item: dict[str, Any],
    rules: FreelanceRules | None = None,
    *,
    today: date | None = None,
) -> FreelanceScore:
    rules = rules or FreelanceRules()
    today = today or datetime.now(timezone.utc).date()
    text = f"{item.get('title', '')} {item.get('description', '')} {item.get('skills', '')}".lower()
    notes: list[str] = []
    score = 0

    capability_hits = sorted(term for term in CAPABILITY_TERMS if term in text)
    if capability_hits:
        points = min(rules.capability_match, 8 + 4 * len(capability_hits))
        score += points
        notes.append(f"Capability match: {', '.join(capability_hits[:5])} (+{points})")
    else:
        return FreelanceScore(
            score=0,
            notes=["No clear match with our web-development capabilities (+0)"],
            effort="Unknown",
        )

    budget_min = item.get("budget_min")
    budget_max = item.get("budget_max")
    currency = (item.get("currency") or "").upper()
    budget_value = budget_max if budget_max is not None else budget_min
    if budget_value is None:
        notes.append("Budget not disclosed; suitability unknown (+0)")
    elif currency and currency != rules.default_currency.upper():
        moderate = min(rules.budget_suitability, 8)
        score += moderate
        notes.append(f"Budget is in {currency}; compare manually with your INR target (+{moderate})")
    else:
        value = float(budget_value)
        if rules.target_budget_min <= value <= rules.target_budget_max:
            score += rules.budget_suitability
            notes.append(f"Budget within target range (+{rules.budget_suitability})")
        elif value < rules.target_budget_min:
            points = max(2, rules.budget_suitability // 2)
            score += points
            notes.append(f"Budget below target range (+{points})")
        else:
            points = max(2, rules.budget_suitability // 3)
            score += points
            notes.append(f"Budget above target range; not automatically ranked higher (+{points})")

    description = str(item.get("description") or "")
    skills = str(item.get("skills") or "")
    clarity = 0
    if len(description) >= 300:
        clarity += 8
    elif len(description) >= 100:
        clarity += 5
    if skills:
        clarity += 4
    if item.get("budget_type"):
        clarity += 3
    clarity = min(rules.scope_clarity, clarity)
    score += clarity
    notes.append(f"Scope clarity (+{clarity})")

    posted = _parse_date(item.get("posted_at"))
    if posted is None:
        notes.append("Posting date unknown; recency not scored (+0)")
    else:
        age = max(0, (today - posted).days)
        if age <= 1:
            points = rules.recency
        elif age <= 3:
            points = int(rules.recency * 0.8)
        elif age <= 7:
            points = int(rules.recency * 0.55)
        elif age <= 14:
            points = int(rules.recency * 0.3)
        else:
            points = 0
        score += points
        notes.append(f"Posted {age} day(s) ago (+{points})")

    if item.get("status_verified") and item.get("project_status") == "Open and verified":
        score += rules.verified_open
        notes.append(f"Status verified as open by the source (+{rules.verified_open})")
    else:
        notes.append("Open status not independently verified (+0)")

    proposals = item.get("proposal_count")
    if proposals is None:
        notes.append("Competition level not disclosed (+0)")
    else:
        count = int(proposals)
        if count <= 5:
            points = rules.low_competition
        elif count <= 15:
            points = max(2, int(rules.low_competition * 0.6))
        elif count <= 30:
            points = max(1, int(rules.low_competition * 0.3))
        else:
            points = 0
        score += points
        notes.append(f"{count} proposal(s) so far (+{points})")

    effort = "Low"
    effort_terms = sum(1 for term in ("ecommerce", "e-commerce", "shopify", "api", "integration", "mobile app") if term in text)
    if effort_terms >= 2 or len(description) > 2500:
        effort = "High"
    elif effort_terms == 1 or len(description) > 1000:
        effort = "Medium"
    if effort == "Low":
        score += rules.manageable_effort
        notes.append(f"Estimated delivery effort: low (+{rules.manageable_effort})")
    else:
        notes.append(f"Estimated delivery effort: {effort.lower()} (+0)")

    final = max(0, min(100, score))
    return FreelanceScore(score=final, notes=notes, effort=effort)


def is_web_development(item: dict[str, Any]) -> bool:
    text = f"{item.get('title', '')} {item.get('description', '')} {item.get('skills', '')}".lower()
    return any(term in text for term in CAPABILITY_TERMS)
