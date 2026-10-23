"""Freelance opportunity search orchestration, filtering and deduplication."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from config import FreelanceRules, Settings
from ..db import Database
from .models import FreelanceOpportunity, FreelanceReport, FreelanceSearch
from .providers import all_providers
from .scoring import is_web_development, score_freelance

log = logging.getLogger(__name__)
ProgressFn = Callable[[str, int, int, str], None]

DEFAULT_PLATFORMS = ["freelancer", "remotive", "arbeitnow"]
META_KEY = "last_successful_freelance_search"


def _terms(value: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[A-Za-z0-9.+#-]+", value or "") if len(term) > 2]


def _within_days(posted_at: str, days: int | None) -> bool:
    if not posted_at or days is None:
        return True
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00")).date()
    except ValueError:
        return True
    return posted >= date.today() - timedelta(days=int(days))


def _passes_filters(item: FreelanceOpportunity, search: FreelanceSearch) -> bool:
    text = f"{item.title} {item.description} {item.skills} {item.experience}".lower()
    keywords = _terms(search.keywords)
    if keywords and not any(term in text for term in keywords):
        return False
    technologies = _terms(search.technologies)
    if technologies and not any(term in text for term in technologies):
        return False
    if not is_web_development(item.to_dict()):
        return False
    if search.verified_only and item.project_status != "Open and verified":
        return False
    if search.project_type and search.project_type != "Any":
        if search.project_type.lower() not in (item.budget_type or "").lower():
            return False
    if not _within_days(item.posted_at, search.posted_within_days):
        return False

    currency = (search.currency or "").upper()
    same_currency = (not currency) or (not item.currency) or item.currency.upper() == currency
    if same_currency and (search.min_budget is not None or search.max_budget is not None):
        if search.min_budget is not None and item.budget_max is not None and item.budget_max < float(search.min_budget):
            return False
        if search.max_budget is not None and item.budget_min is not None and item.budget_min > float(search.max_budget):
            return False
    return True


def provider_statuses(settings: Settings):
    return [provider.status() for provider in all_providers(settings).values()]


def search_opportunities(
    db: Database,
    settings: Settings,
    search: FreelanceSearch,
    *,
    rules: FreelanceRules | None = None,
    progress: ProgressFn | None = None,
) -> FreelanceReport:
    rules = rules or settings.load_freelance_rules()
    providers = all_providers(settings)
    selected = [name for name in (search.platforms or DEFAULT_PLATFORMS) if name in providers]
    if search.include_demo and "demo" not in selected:
        selected.append("demo")
    if not selected:
        selected = DEFAULT_PLATFORMS

    previous_success = db.get_meta(META_KEY, "")
    report = FreelanceReport(previous_search_at=previous_success)
    candidates: list[FreelanceOpportunity] = []
    successful_providers = 0
    total = len(selected)

    for index, name in enumerate(selected, start=1):
        provider = providers[name]
        if progress:
            progress("freelance", index - 1, total, f"Checking {provider.label}")
        if name == "demo" and not search.include_demo:
            continue
        try:
            result = provider.search(search.keywords.strip() or "website development", search.max_results)
        except Exception as exc:  # one provider must never break the others
            report.failed_providers.append(name)
            report.provider_messages.append(f"{provider.label}: failed ({type(exc).__name__})")
            log.warning("Freelance provider %s failed: %s", name, type(exc).__name__)
            continue
        if result.status in {"ok", "rate-limited"}:
            successful_providers += 1
        if result.error:
            report.failed_providers.append(name) if result.status in {"error", "configuration-required", "unavailable"} else None
            report.provider_messages.append(f"{provider.label}: {result.error}")
        for item in result.opportunities:
            if _passes_filters(item, search):
                candidates.append(item)
        if progress:
            progress("freelance", index, total, f"Checked {provider.label}: {len(result.opportunities)} listing(s)")

    scored: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        if item.is_demo and not search.include_demo:
            continue
        key = f"{item.platform}|{item.external_id or item.url}"
        if key in seen:
            continue
        seen.add(key)
        score = score_freelance(item.to_dict(), rules)
        item.match_score = score.score
        item.score_notes = score.explanation()
        scored.append(item.to_dict())

    report.found = len(scored)
    new_count, updated = db.upsert_freelance_opportunities(scored)
    report.new = new_count
    report.updated = updated
    db.mark_new_freelance(previous_success)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report.checked_at = now
    if successful_providers:
        db.set_meta(META_KEY, now)

    report.limitations = [
        "Only public APIs and documented endpoints are queried. Upwork, PeoplePerHour and Guru require manual use or credentials.",
        "Job-board listings (Remotive, Arbeitnow) are jobs, not freelance projects, and their open status may change.",
        "Budgets are shown exactly as published. Currencies are never converted with invented exchange rates.",
        "Application deadlines are shown only when the source provides them.",
        "This tool never submits bids or messages; review and apply manually.",
    ]
    if report.new:
        report.limitations.append(f"{report.new} new listing(s) were added since the previous successful search.")
    return report
