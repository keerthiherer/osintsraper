"""Transparent, configurable 0-100 lead scoring."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from config import (
    WEBSITE_NO_WEBSITE,
    WEBSITE_UNREACHABLE,
    ScoringRules,
)


@dataclass
class ScoreResult:
    score: int
    priority: str
    notes: list[str] = field(default_factory=list)


def priority_for(score: int) -> str:
    if score >= 80:
        return "High priority"
    if score >= 60:
        return "Medium priority"
    return "Low priority"


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
    socials = record.get("socials") or []
    return [s for s in socials if isinstance(s, dict)]


def score_business(
    record: dict[str, Any],
    rules: ScoringRules | None = None,
    *,
    today: date | None = None,
) -> ScoreResult:
    rules = rules or ScoringRules()
    today = today or datetime.now(timezone.utc).date()
    score = 0
    notes: list[str] = []

    status = record.get("website_status") or "Unknown"
    website = (record.get("website") or "").strip()
    if status == WEBSITE_NO_WEBSITE:
        score += rules.no_website
        notes.append(f"No website listed (+{rules.no_website})")
    elif status == WEBSITE_UNREACHABLE and website:
        score += rules.broken_website
        notes.append(f"Website unreachable (+{rules.broken_website})")

    socials = _socials(record)
    verified_audience = [
        s for s in socials
        if s.get("followers_verified")
        and s.get("followers") is not None
        and int(s["followers"]) >= rules.min_followers
    ]
    if verified_audience:
        best = max(verified_audience, key=lambda s: int(s["followers"]))
        score += rules.verified_followers
        notes.append(
            f"Verified social audience {int(best['followers']):,} "
            f"(>= {rules.min_followers:,}) (+{rules.verified_followers})"
        )

    cutoff = today - timedelta(days=rules.active_days)
    active = []
    for social in socials:
        if not social.get("activity_verified"):
            continue
        last_active = _parse_date(social.get("last_active"))
        if last_active and last_active >= cutoff:
            active.append(social)
    if active:
        newest = max(active, key=lambda s: _parse_date(s.get("last_active")) or today)
        score += rules.recent_activity
        notes.append(
            f"Recent verified activity on {newest['platform']} "
            f"({newest['last_active']}) (+{rules.recent_activity})"
        )

    if (record.get("phone") or "").strip():
        score += rules.phone
        notes.append(f"Public phone available (+{rules.phone})")
    if (record.get("email") or "").strip():
        score += rules.email
        notes.append(f"Public email available (+{rules.email})")

    rating = record.get("rating")
    reviews = record.get("review_count")
    if (
        rating is not None
        and reviews is not None
        and float(rating) >= rules.rating_threshold
        and int(reviews) >= rules.review_threshold
    ):
        score += rules.rating_reviews
        notes.append(
            f"Strong local reputation ({float(rating):.1f} stars, "
            f"{int(reviews)} reviews) (+{rules.rating_reviews})"
        )

    strong_matches = [
        s for s in socials
        if (s.get("confidence") or 0) >= rules.strong_match_confidence
        and s.get("source") in {"website", "demo", "user"}
        and s.get("url")
    ]
    if strong_matches:
        score += rules.strong_social_match
        notes.append(f"Strong social profile match (+{rules.strong_social_match})")

    final = max(0, min(100, score))
    return ScoreResult(score=final, priority=priority_for(final), notes=notes)
