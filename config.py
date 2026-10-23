"""Central configuration, scoring rules and platform settings.

All weights are deliberately transparent and configurable. Nothing in this
module is a prediction of a business's actual revenue or purchase intent.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

WEBSITE_NO_WEBSITE = "No website listed"
WEBSITE_REACHABLE = "Website reachable"
WEBSITE_UNREACHABLE = "Website unreachable"
WEBSITE_CHECK_FAILED = "Website check failed"
WEBSITE_UNKNOWN = "Unknown"

WEBSITE_STATUSES = [
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
    WEBSITE_CHECK_FAILED,
    WEBSITE_UNKNOWN,
]

SOCIAL_PLATFORMS = ["instagram", "facebook", "linkedin"]

CRM_STATUSES = [
    "New lead",
    "Qualified",
    "Contacted",
    "Replied",
    "Meeting scheduled",
    "Quotation sent",
    "Negotiation",
    "Won",
    "Lost",
    "Follow-up required",
]

BUDGET_FITS = ["limited", "moderate", "higher-capability", "unknown"]

REVENUE_CATEGORIES = [
    "Verified revenue disclosed publicly",
    "Third-party revenue estimate with a cited source",
    "Estimated business-size category only",
    "Insufficient evidence",
]

OPPORTUNITY_CLASSES = [
    "High-priority opportunity",
    "Potential opportunity",
    "Needs more research",
    "Low-priority opportunity",
]

FREELANCE_STATUSES = [
    "Open and verified",
    "Possibly open; status unconfirmed",
    "Closed or expired",
    "Failed to check",
    "Demo sample (fictional)",
]

OPPORTUNITY_RULES_FILE = "opportunity_rules.json"
FREELANCE_RULES_FILE = "freelance_rules.json"
PRICING_CATALOGUE_FILE = "pricing_catalogue.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class ScoringRules:
    no_website: int = 30
    broken_website: int = 20
    verified_followers: int = 15
    recent_activity: int = 10
    phone: int = 5
    email: int = 5
    rating_reviews: int = 10
    strong_social_match: int = 5
    min_followers: int = 2000
    active_days: int = 30
    rating_threshold: float = 4.0
    review_threshold: int = 20
    strong_match_confidence: float = 0.8


@dataclass
class OpportunityRules:
    """Configurable website-need heuristics. Weights are not validated predictors."""

    no_website: int = 20
    website_problems: int = 15
    recent_activity: int = 10
    verified_audience: int = 10
    multiple_locations_or_catalogue: int = 10
    promotes_services: int = 10
    contact_available: int = 5
    established_operations: int = 10
    expansion: int = 10
    min_followers: int = 2000
    active_days: int = 30
    review_threshold: int = 30
    catalogue_threshold: int = 20
    locations_threshold: int = 2
    high_threshold: int = 75
    potential_threshold: int = 50
    low_threshold: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FreelanceRules:
    """Configurable scoring for freelance marketplace opportunities."""

    capability_match: int = 30
    budget_suitability: int = 20
    scope_clarity: int = 15
    recency: int = 15
    verified_open: int = 10
    low_competition: int = 10
    manageable_effort: int = 5
    target_budget_min: int = 15000
    target_budget_max: int = 250000
    default_currency: str = "INR"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Settings:
    base_dir: Path = BASE_DIR
    db_path: Path = field(default_factory=lambda: BASE_DIR / os.getenv("DB_PATH", "data/mindsmiths.db"))
    log_path: Path = field(default_factory=lambda: BASE_DIR / os.getenv("LOG_PATH", "logs/mindsmiths.log"))
    demo_csv: Path = field(default_factory=lambda: BASE_DIR / "data" / "sample_leads.csv")
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    opportunity_rules_path: Path = field(
        default_factory=lambda: BASE_DIR / "data" / OPPORTUNITY_RULES_FILE
    )
    freelance_rules_path: Path = field(
        default_factory=lambda: BASE_DIR / "data" / FREELANCE_RULES_FILE
    )
    pricing_catalogue_path: Path = field(
        default_factory=lambda: BASE_DIR / "data" / PRICING_CATALOGUE_FILE
    )
    request_timeout: int = field(default_factory=lambda: _env_int("REQUEST_TIMEOUT", 15))
    request_delay: float = field(default_factory=lambda: _env_float("REQUEST_DELAY", 1.0))
    max_workers: int = field(default_factory=lambda: max(1, min(_env_int("MAX_WORKERS", 4), 8)))
    serpapi_key: str = field(default_factory=lambda: os.getenv("SERPAPI_KEY", "").strip())
    overpass_url: str = field(
        default_factory=lambda: os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
    )
    default_city: str = field(default_factory=lambda: os.getenv("DEFAULT_CITY", "Chennai"))
    web_search_enabled: bool = field(default_factory=lambda: _env_bool("WEB_SEARCH_ENABLED", True))
    web_search_delay: float = field(default_factory=lambda: _env_float("WEB_SEARCH_DELAY", 1.2))
    web_search_results: int = field(
        default_factory=lambda: max(3, min(_env_int("WEB_SEARCH_RESULTS", 10), 20))
    )
    web_search_engine: str = field(
        default_factory=lambda: os.getenv("WEB_SEARCH_ENGINE", "auto").strip().lower()
    )
    user_agent: str = (
        "MindSmithsLeadIntelligence/1.0 (local business research; contact: sales@mindsmiths.example)"
    )
    scoring: ScoringRules = field(default_factory=ScoringRules)
    opportunity: OpportunityRules = field(default_factory=OpportunityRules)
    freelance: FreelanceRules = field(default_factory=FreelanceRules)
    freelancer_api_url: str = field(
        default_factory=lambda: os.getenv(
            "FREELANCER_API_URL",
            "https://www.freelancer.com/api/projects/0.1/projects/active/",
        ).strip()
    )
    remotive_api_url: str = field(
        default_factory=lambda: os.getenv(
            "REMOTIVE_API_URL", "https://remotive.com/api/remote-jobs"
        ).strip()
    )
    arbeitnow_api_url: str = field(
        default_factory=lambda: os.getenv(
            "ARBEITNOW_API_URL", "https://www.arbeitnow.com/api/job-board-api"
        ).strip()
    )
    upwork_access_token: str = field(
        default_factory=lambda: os.getenv("UPWORK_ACCESS_TOKEN", "").strip()
    )
    upwork_graphql_url: str = field(
        default_factory=lambda: os.getenv(
            "UPWORK_GRAPHQL_URL", "https://api.upwork.com/graphql"
        ).strip()
    )
    freelance_fetch_details: bool = field(
        default_factory=lambda: _env_bool("FREELANCE_FETCH_DETAILS", False)
    )
    company_name: str = "MindSmiths"
    company_parent: str = "Melouz Technologies Pvt Ltd"
    company_contact: str = field(
        default_factory=lambda: os.getenv("COMPANY_CONTACT", "sales@mindsmiths.example")
    )
    company_website: str = field(
        default_factory=lambda: os.getenv("COMPANY_WEBSITE", "https://mindsmiths.example")
    )

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_opportunity_rules(self) -> OpportunityRules:
        return load_dataclass(self.opportunity_rules_path, OpportunityRules, self.opportunity)

    def load_freelance_rules(self) -> FreelanceRules:
        return load_dataclass(self.freelance_rules_path, FreelanceRules, self.freelance)


def load_dataclass(path: str | Path, cls, default):
    """Load a dataclass from JSON, ignoring unknown keys and invalid files."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default
    if not isinstance(payload, dict):
        return default
    valid = {field_name for field_name in cls.__dataclass_fields__}
    values = {key: value for key, value in payload.items() if key in valid}
    try:
        return cls(**values)
    except (TypeError, ValueError):
        return default


def save_dataclass(path: str | Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
