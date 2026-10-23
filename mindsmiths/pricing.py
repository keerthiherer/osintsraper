"""Configurable pricing catalogue for MindSmiths quotations.

Prices are INR defaults. The sales team can edit them in Settings; the
catalogue is stored as JSON so prices are never scattered through the UI.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PricingCatalogue:
    currency: str = "INR"
    minimum_project_price: int = 8_000
    maximum_project_price: int = 250_000
    validity_days: int = 30
    included_pages: int = 5
    per_extra_page: int = 1_500
    base_prices: dict[str, int] = field(default_factory=lambda: {
        "landing": 12_000,
        "static": 18_000,
        "business": 28_000,
        "dynamic": 45_000,
        "ecommerce": 68_000,
    })
    feature_prices: dict[str, int] = field(default_factory=lambda: {
        "booking_enquiry": 5_000,
        "cms_admin": 8_000,
        "custom_integration": 10_000,
        "content_page": 2_000,
        "seo_setup": 5_000,
        "additional_support": 3_000,
    })
    maintenance_monthly: int = 1_500
    hosting_domain_annual: int = 6_000
    delivery_days: dict[str, int] = field(default_factory=lambda: {
        "landing": 7,
        "static": 10,
        "business": 18,
        "dynamic": 28,
        "ecommerce": 35,
    })
    payment_milestones: list[dict[str, Any]] = field(default_factory=lambda: [
        {"label": "Advance on approval", "percent": 40},
        {"label": "Design/development milestone", "percent": 40},
        {"label": "Launch and handover", "percent": 20},
    ])
    exclusions: list[str] = field(default_factory=lambda: [
        "Domain registration and hosting renewal unless explicitly included",
        "Paid stock photography, premium plugins and third-party licence fees",
        "Content writing beyond the agreed page count",
        "Ongoing advertising spend and paid API usage",
        "Major scope changes after written approval",
    ])
    assumptions: list[str] = field(default_factory=lambda: [
        "Client supplies brand assets, product/service information and approvals.",
        "One consolidated round of revisions is included at each milestone.",
        "Timeline starts after the advance payment and content handover.",
        "Third-party integrations depend on provider approval and API availability.",
    ])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def base_price(self, website_type: str) -> int:
        return int(self.base_prices.get(website_type, self.base_prices.get("business", 28_000)))

    def delivery(self, website_type: str) -> int:
        return int(self.delivery_days.get(website_type, 18))


def default_catalogue() -> PricingCatalogue:
    return PricingCatalogue()


def load_catalogue(path: str | Path) -> PricingCatalogue:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default_catalogue()
    if not isinstance(payload, dict):
        return default_catalogue()
    default = default_catalogue()
    values: dict[str, Any] = {}
    for key in default.__dataclass_fields__:
        if key in payload:
            values[key] = payload[key]
    try:
        catalogue = PricingCatalogue(**values)
    except (TypeError, ValueError):
        return default
    if not catalogue.base_prices:
        catalogue.base_prices = default.base_prices
    if not catalogue.feature_prices:
        catalogue.feature_prices = default.feature_prices
    return catalogue


def save_catalogue(path: str | Path, catalogue: PricingCatalogue) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalogue.to_dict(), indent=2), encoding="utf-8")
