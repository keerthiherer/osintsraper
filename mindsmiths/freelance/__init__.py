"""Compliant freelance opportunity connectors and scoring."""

from .models import (
    FreelanceOpportunity,
    FreelanceReport,
    FreelanceSearch,
    ProviderStatus,
)
from .providers import all_providers
from .scoring import score_freelance
from .service import provider_statuses, search_opportunities

__all__ = [
    "FreelanceOpportunity",
    "FreelanceReport",
    "FreelanceSearch",
    "ProviderStatus",
    "all_providers",
    "provider_statuses",
    "score_freelance",
    "search_opportunities",
]
