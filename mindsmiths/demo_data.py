"""Load fictional demo leads from the sample CSV."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .models import (
    Business,
    SocialProfile,
    clean_text,
    normalize_website,
    parse_bool,
    parse_float,
    parse_int,
)


def _social_from_row(row: dict[str, Any], platform: str) -> SocialProfile | None:
    url = clean_text(row.get(f"{platform}_url"))
    if not url:
        return None
    followers = parse_int(row.get(f"{platform}_followers"))
    verified = parse_bool(row.get(f"{platform}_verified")) and followers is not None
    activity = parse_bool(row.get(f"{platform}_activity_verified"))
    last_active = clean_text(row.get(f"{platform}_last_active")) or None
    return SocialProfile(
        platform=platform,
        url=url,
        followers=followers,
        followers_verified=verified,
        activity_verified=activity and last_active is not None,
        last_active=last_active,
        confidence=parse_float(row.get(f"{platform}_confidence")) or 0.0,
        source="demo",
    )


def load_sample_businesses(path: str | Path) -> list[Business]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    businesses: list[Business] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = clean_text(row.get("name"))
            if not name:
                continue
            socials = []
            for platform in ("instagram", "facebook", "linkedin"):
                social = _social_from_row(row, platform)
                if social:
                    socials.append(social)
            issues = [
                clean_text(part) for part in clean_text(row.get("website_issues")).split(";")
                if clean_text(part)
            ]
            business = Business(
                name=name,
                category=clean_text(row.get("category")),
                address=clean_text(row.get("address")),
                city=clean_text(row.get("city")),
                locality=clean_text(row.get("locality")),
                phone=clean_text(row.get("phone")),
                email=clean_text(row.get("email")),
                website=normalize_website(row.get("website")),
                listing_url=clean_text(row.get("listing_url")),
                rating=parse_float(row.get("rating")),
                review_count=parse_int(row.get("review_count")),
                opening_hours=clean_text(row.get("opening_hours")),
                source="demo",
                collected_at=clean_text(row.get("collected_at")) or "2026-10-01",
                last_seen_at=clean_text(row.get("collected_at")) or "2026-10-01",
                search_query="Demo dataset (fictional)",
                website_status=clean_text(row.get("website_status")) or "Unknown",
                website_http_status=parse_int(row.get("website_http_status")),
                website_title=clean_text(row.get("website_title")),
                website_issues=issues,
                contact_page=clean_text(row.get("contact_page")),
                form_url=clean_text(row.get("form_url")),
                website_source="demo" if clean_text(row.get("website")) else "",
                phone_source="demo" if clean_text(row.get("phone")) else "",
                email_source="demo" if clean_text(row.get("email")) else "",
                notes=clean_text(row.get("notes")),
                socials=socials,
            )
            businesses.append(business.finalize())
    return businesses
