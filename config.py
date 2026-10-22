"""Central configuration and scoring rules for MindSmiths Lead Intelligence."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
class Settings:
    base_dir: Path = BASE_DIR
    db_path: Path = field(default_factory=lambda: BASE_DIR / os.getenv("DB_PATH", "data/mindsmiths.db"))
    log_path: Path = field(default_factory=lambda: BASE_DIR / os.getenv("LOG_PATH", "logs/mindsmiths.log"))
    demo_csv: Path = field(default_factory=lambda: BASE_DIR / "data" / "sample_leads.csv")
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

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
