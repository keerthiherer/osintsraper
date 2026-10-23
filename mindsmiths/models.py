"""Data models and normalisation helpers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower()).strip()


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        return digits
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    return ""


def normalize_website(value: str | None) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    return value


def domain_from_url(value: str | None) -> str:
    url = normalize_website(value)
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def normalize_url(value: str | None) -> str:
    url = normalize_website(value)
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


def identity_key(name: str, city: str, locality: str = "") -> str:
    return f"{slug(name)}|{slug(locality or city)}"


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip().split()[0])
    except (ValueError, IndexError):
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


@dataclass
class SocialProfile:
    platform: str
    url: str
    followers: int | None = None
    followers_verified: bool = False
    activity_verified: bool = False
    last_active: str | None = None
    confidence: float = 0.0
    source: str = ""
    collected_at: str = field(default_factory=now_iso)

    def followers_label(self) -> str:
        if self.followers is not None and self.followers_verified:
            return f"{self.followers:,}"
        if self.followers is not None:
            return f"~{self.followers:,} (Needs manual verification)"
        return "Needs manual verification"


@dataclass
class Business:
    name: str
    category: str = ""
    address: str = ""
    city: str = ""
    locality: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    listing_url: str = ""
    rating: float | None = None
    review_count: int | None = None
    opening_hours: str = ""
    source: str = ""
    collected_at: str = field(default_factory=now_iso)
    last_seen_at: str = field(default_factory=now_iso)
    search_query: str = ""
    website_status: str = "Unknown"
    website_http_status: int | None = None
    website_final_url: str = ""
    website_title: str = ""
    website_issues: list[str] = field(default_factory=list)
    contact_page: str = ""
    form_url: str = ""
    website_source: str = ""
    phone_source: str = ""
    email_source: str = ""
    notes: str = ""
    status: str = "new"
    excluded: bool = False
    socials: list[SocialProfile] = field(default_factory=list)

    # Business-size and website-audit evidence (unknown = None, never zero).
    number_of_locations: int | None = None
    catalogue_size: int | None = None
    product_price_min: float | None = None
    product_price_max: float | None = None
    services_summary: str = ""
    has_booking: bool | None = None
    has_enquiry: bool | None = None
    promotes_services: bool | None = None
    expansion_signal: bool | None = None
    established_signal: bool | None = None
    website_response_ms: int | None = None
    website_page_bytes: int | None = None
    has_cta: bool | None = None

    # Explicit revenue disclosures (must always be sourced by the user).
    verified_revenue: float | None = None
    verified_revenue_source: str = ""
    third_party_revenue: float | None = None
    third_party_revenue_source: str = ""

    def finalize(self) -> "Business":
        self.name = clean_text(self.name)
        self.category = clean_text(self.category)
        self.address = clean_text(self.address)
        self.city = clean_text(self.city)
        self.locality = clean_text(self.locality)
        self.phone = clean_text(self.phone)
        self.email = clean_text(self.email).lower()
        self.website = normalize_website(self.website)
        self.listing_url = normalize_url(self.listing_url)
        self.opening_hours = clean_text(self.opening_hours)
        self.website_final_url = normalize_url(self.website_final_url)
        self.contact_page = normalize_url(self.contact_page)
        self.form_url = normalize_url(self.form_url)
        self.search_query = clean_text(self.search_query)
        self.source = clean_text(self.source) or "unknown"
        self.website_status = self.website_status or "Unknown"
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("socials", None)
        data["identity_key"] = identity_key(self.name, self.city, self.locality)
        data["domain"] = domain_from_url(self.website)
        data["phone_norm"] = normalize_phone(self.phone)
        data["website_issues"] = "; ".join(self.website_issues)
        return data

