"""Freelance opportunity data models and provider status."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FreelanceOpportunity:
    platform: str
    title: str
    url: str
    external_id: str = ""
    description: str = ""
    posted_at: str = ""
    deadline: str = ""
    budget_min: float | None = None
    budget_max: float | None = None
    budget_type: str = ""
    currency: str = ""
    skills: str = ""
    experience: str = ""
    client_info: str = ""
    proposal_count: int | None = None
    project_status: str = "Possibly open; status unconfirmed"
    status_verified: bool = False
    last_checked_at: str = ""
    source_query: str = ""
    is_demo: bool = False
    match_score: int = 0
    score_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderStatus:
    name: str
    label: str
    state: str  # available | configured | configuration-required | limited | unavailable
    detail: str
    docs_url: str = ""
    requires_key: bool = False


@dataclass
class FreelanceSearch:
    keywords: str = "website development"
    platforms: list[str] = field(default_factory=list)
    min_budget: float | None = None
    max_budget: float | None = None
    currency: str = "INR"
    project_type: str = "Any"
    technologies: str = ""
    posted_within_days: int | None = 30
    verified_only: bool = False
    max_results: int = 50
    include_demo: bool = False


@dataclass
class ProviderResult:
    provider: str
    opportunities: list[FreelanceOpportunity] = field(default_factory=list)
    error: str = ""
    status: str = "ok"
    checked_at: str = ""


@dataclass
class FreelanceReport:
    found: int = 0
    new: int = 0
    updated: int = 0
    failed_providers: list[str] = field(default_factory=list)
    provider_messages: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    previous_search_at: str = ""
    checked_at: str = ""

    def summary(self) -> str:
        base = f"{self.found} matching listing(s), {self.new} new, {self.updated} updated"
        if self.failed_providers:
            base += f"; {len(self.failed_providers)} provider(s) unavailable"
        return base
