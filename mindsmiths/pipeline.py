"""End-to-end search pipeline with progress, safe concurrency and persistence."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from config import ScoringRules, Settings
from .db import Database
from .discovery import (
    BaseProvider,
    DiscoveryError,
    SearchParams,
    get_provider,
    validate_search,
)
from .enrichment import enrich_business
from .models import Business, SocialProfile
from .scoring import score_business

log = logging.getLogger(__name__)
ProgressFn = Callable[[str, int, int, str], None]


@dataclass
class SearchReport:
    provider: str
    query: str
    found: int = 0
    new: int = 0
    updated: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_seconds: float = 0.0

    def summary(self) -> str:
        return (
            f"{self.found} found, {self.new} new, {self.updated} updated, "
            f"{self.failed} failed, {self.skipped} skipped in {self.duration_seconds:.1f}s"
        )


def provider_limitations(provider: str, params: SearchParams) -> list[str]:
    notes = [
        "Results are limited to what the selected public source returns; this is not a complete market census.",
        "Follower counts and activity are only shown when verified from a permitted source; otherwise they need manual verification.",
    ]
    if provider == "openstreetmap":
        notes.extend([
            "OpenStreetMap is free and requires no key, but it does not provide Google ratings, reviews or Google Maps place URLs.",
            "Coverage and contact data vary by locality; businesses absent from OpenStreetMap will not appear.",
        ])
    elif provider == "serpapi":
        notes.append("SerpAPI results depend on your plan, quota and Google Maps coverage.")
    elif provider == "demo":
        notes = ["Demo mode imports fictional sample records only. It does not perform live discovery."]
    if params.max_results >= 200:
        notes.append("A 200-result cap is enforced to protect public data sources.")
    return notes


def run_search(
    db: Database,
    settings: Settings,
    params: SearchParams,
    *,
    rules: ScoringRules | None = None,
    progress: ProgressFn | None = None,
) -> SearchReport:
    errors = validate_search(params)
    if errors:
        raise ValueError(" ".join(errors))

    started = time.monotonic()
    report = SearchReport(provider=params.provider, query=params.query)
    report.limitations = provider_limitations(params.provider, params)
    rules = rules or settings.scoring

    def notify(stage: str, current: int, total: int, message: str) -> None:
        if progress:
            progress(stage, current, total, message)

    notify("discover", 0, 1, f"Searching: {params.query}")
    try:
        provider: BaseProvider = get_provider(settings, params.provider)
        businesses = provider.search(params, lambda message: notify("discover", 0, 1, message))
    except DiscoveryError as exc:
        report.errors.append(str(exc))
        report.duration_seconds = time.monotonic() - started
        log.warning("Discovery failed: %s", exc)
        raise
    except Exception as exc:
        report.errors.append(f"Discovery failed: {type(exc).__name__}")
        report.duration_seconds = time.monotonic() - started
        log.exception("Unexpected discovery failure")
        raise DiscoveryError(f"Discovery failed: {type(exc).__name__}") from exc

    report.found = len(businesses)
    if not businesses:
        report.limitations.append("The source returned zero businesses for this query and location.")
        report.duration_seconds = time.monotonic() - started
        notify("done", 0, 0, "No results returned by the source")
        return report

    if params.provider == "demo":
        enriched = [business for business in businesses if business.name]
        report.skipped = len(businesses) - len(enriched)
    else:
        enriched = []
        total = len(businesses)
        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            future_map = {
                executor.submit(enrich_business, business, settings): business
                for business in businesses
            }
            for index, future in enumerate(as_completed(future_map), start=1):
                business = future_map[future]
                try:
                    result = future.result()
                    if result.name:
                        enriched.append(result)
                    else:
                        report.skipped += 1
                except Exception as exc:
                    report.failed += 1
                    report.errors.append(f"{business.name}: {type(exc).__name__}")
                    log.warning("Enrichment failed for %s: %s", business.name, type(exc).__name__)
                notify("enrich", index, total, f"Checked {index}/{total}: {business.name}")

    total = len(enriched)
    for index, business in enumerate(enriched, start=1):
        try:
            business_id, action = db.upsert_business(business)
            if action == "new":
                report.new += 1
            else:
                report.updated += 1
            saved = db.get_business(business_id)
            if saved is not None:
                result = score_business(saved, rules)
                db.update_score(business_id, result.score, result.priority, result.notes)
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{business.name}: database error ({type(exc).__name__})")
            log.exception("Database upsert failed for %s", business.name)
        notify("save", index, total, f"Saved {index}/{total}: {business.name}")

    report.duration_seconds = time.monotonic() - started
    notify(
        "done",
        total,
        total,
        f"Complete: {report.new} new, {report.updated} updated, {report.failed} failed",
    )
    log.info(
        "Search provider=%s query=%r found=%d new=%d updated=%d failed=%d",
        params.provider, params.query, report.found, report.new, report.updated, report.failed,
    )
    return report


def rescore_all(db: Database, rules: ScoringRules) -> int:
    count = 0
    for record in db.list_businesses(limit=100000, include_excluded=True):
        result = score_business(record, rules)
        db.update_score(record["id"], result.score, result.priority, result.notes)
        count += 1
    return count


def _record_to_business(record: dict) -> Business:
    socials = []
    for item in record.get("socials") or []:
        socials.append(SocialProfile(
            platform=item.get("platform", ""),
            url=item.get("url", ""),
            followers=item.get("followers"),
            followers_verified=bool(item.get("followers_verified")),
            activity_verified=bool(item.get("activity_verified")),
            last_active=item.get("last_active"),
            confidence=float(item.get("confidence") or 0),
            source=item.get("source", ""),
            collected_at=item.get("collected_at", ""),
        ))
    issues = [part.strip() for part in (record.get("website_issues") or "").split(";") if part.strip()]
    return Business(
        name=record.get("name", ""),
        category=record.get("category", ""),
        address=record.get("address", ""),
        city=record.get("city", ""),
        locality=record.get("locality", ""),
        phone=record.get("phone", ""),
        email=record.get("email", ""),
        website=record.get("website", ""),
        listing_url=record.get("listing_url", ""),
        rating=record.get("rating"),
        review_count=record.get("review_count"),
        opening_hours=record.get("opening_hours", ""),
        source=record.get("source", ""),
        collected_at=record.get("collected_at", ""),
        last_seen_at=record.get("last_seen_at", ""),
        search_query=record.get("search_query", ""),
        website_status=record.get("website_status", "Unknown"),
        website_http_status=record.get("website_http_status"),
        website_final_url=record.get("website_final_url", ""),
        website_title=record.get("website_title", ""),
        website_issues=issues,
        contact_page=record.get("contact_page", ""),
        form_url=record.get("form_url", ""),
        website_source=record.get("website_source", ""),
        phone_source=record.get("phone_source", ""),
        email_source=record.get("email_source", ""),
        notes=record.get("notes", ""),
        status=record.get("status", "new"),
        excluded=bool(record.get("excluded")),
        socials=socials,
    )


def re_enrich_all(
    db: Database,
    settings: Settings,
    rules: ScoringRules,
    *,
    progress: ProgressFn | None = None,
    limit: int = 500,
) -> int:
    """Refresh contacts, socials and website checks for stored leads."""
    records = db.list_businesses(limit=limit, include_excluded=True)
    total = len(records)
    enriched = 0
    with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
        futures = {
            executor.submit(enrich_business, _record_to_business(record), settings): record
            for record in records
        }
        for index, future in enumerate(as_completed(futures), start=1):
            record = futures[future]
            try:
                business = future.result()
                business_id, _ = db.upsert_business(business)
                saved = db.get_business(business_id)
                if saved is not None:
                    result = score_business(saved, rules)
                    db.update_score(business_id, result.score, result.priority, result.notes)
                    enriched += 1
                if progress:
                    progress("enrich", index, total, f"Refreshed {index}/{total}: {record.get('name', '')}")
            except Exception as exc:
                log.warning("Re-enrichment failed for %s: %s", record.get("name", ""), type(exc).__name__)
                if progress:
                    progress("enrich", index, total, f"Failed {index}/{total}: {record.get('name', '')}")
    return enriched
