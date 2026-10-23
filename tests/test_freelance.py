from datetime import date

from config import FreelanceRules, Settings
from mindsmiths.db import Database
from mindsmiths.freelance.models import (
    FreelanceOpportunity,
    FreelanceSearch,
    ProviderResult,
)
from mindsmiths.freelance.scoring import is_web_development, score_freelance
from mindsmiths.freelance.service import search_opportunities
import mindsmiths.freelance.service as service_module

TODAY = date(2026, 10, 23)


def freelance_item(external_id="1", **overrides):
    base = {
        "platform": "Fake",
        "external_id": external_id,
        "title": "WordPress website redesign",
        "url": f"https://example.invalid/jobs/{external_id}",
        "description": (
            "We need a WordPress website redesign with web design, landing page and SEO work. "
            + "Describe your approach and relevant examples. " * 8
        ),
        "posted_at": "2026-10-23",
        "budget_min": 25_000,
        "budget_max": 40_000,
        "budget_type": "Fixed price",
        "currency": "INR",
        "skills": "WordPress, SEO, Landing Page",
        "project_status": "Open and verified",
        "status_verified": True,
        "proposal_count": 3,
        "source_query": "website",
    }
    base.update(overrides)
    return FreelanceOpportunity(**base)


def test_freelance_scoring_rewards_relevant_recent_low_competition_work():
    item = freelance_item().to_dict()
    result = score_freelance(item, FreelanceRules(), today=TODAY)
    assert result.score == 100
    assert result.effort == "Low"
    assert any("Capability match" in note for note in result.notes)
    assert any("Budget within target range" in note for note in result.notes)
    assert any("Status verified" in note for note in result.notes)


def test_freelance_scoring_does_not_convert_currency_or_inflate_high_budgets():
    usd = freelance_item(currency="USD").to_dict()
    high = freelance_item(budget_min=500_000, budget_max=900_000).to_dict()
    usd_score = score_freelance(usd, FreelanceRules(), today=TODAY)
    high_score = score_freelance(high, FreelanceRules(), today=TODAY)
    assert any("compare manually" in note for note in usd_score.notes)
    assert any("above target range" in note for note in high_score.notes)
    assert high_score.score < 100


def test_freelance_scoring_ignores_unknown_status_and_recency():
    item = freelance_item(
        project_status="Possibly open; status unconfirmed",
        status_verified=False,
        posted_at="",
    ).to_dict()
    result = score_freelance(item, FreelanceRules(), today=TODAY)
    assert any("not independently verified" in note for note in result.notes)
    assert any("Posting date unknown" in note for note in result.notes)
    assert not any("Status verified" in note for note in result.notes)


def test_non_web_listing_is_not_treated_as_a_match():
    item = {"title": "Accountant required", "description": "Tax filing", "skills": "Accounting"}
    assert is_web_development(item) is False
    assert score_freelance(item, FreelanceRules(), today=TODAY).score == 0


class FakeProvider:
    name = "fake"
    label = "Fake provider"

    def __init__(self, opportunities=None, error=None, raise_error=False):
        self._opportunities = opportunities or []
        self._error = error
        self._raise = raise_error

    def search(self, query, limit=50):
        if self._raise:
            raise RuntimeError("provider down")
        return ProviderResult(
            provider=self.name,
            opportunities=self._opportunities,
            error=self._error or "",
            status="error" if self._error else "ok",
        )


def test_freelance_service_filters_deduplicates_and_marks_new(tmp_path, monkeypatch):
    db = Database(tmp_path / "leads.db")
    settings = Settings()
    duplicate = freelance_item("same-id")
    provider = FakeProvider([duplicate, freelance_item("same-id"), freelance_item("other-id")])
    monkeypatch.setattr(service_module, "all_providers", lambda settings: {"fake": provider})

    search = FreelanceSearch(
        keywords="website",
        platforms=["fake"],
        include_demo=False,
        posted_within_days=None,
        max_results=10,
    )
    report = search_opportunities(db, settings, search, rules=FreelanceRules())
    assert report.found == 2
    assert report.new == 2
    assert report.updated == 0
    rows = db.list_freelance(include_demo=False)
    assert len(rows) == 2
    assert all(row["is_new"] == 1 for row in rows)
    assert all(row["match_score"] > 0 for row in rows)
    assert any("never submits bids" in item for item in report.limitations)

    second = search_opportunities(db, settings, search, rules=FreelanceRules())
    assert second.found == 2
    assert second.new == 0
    assert second.updated == 2
    assert all(row["is_new"] == 0 for row in db.list_freelance(include_demo=False))


def test_freelance_service_isolates_provider_failures(tmp_path, monkeypatch):
    db = Database(tmp_path / "leads.db")
    settings = Settings()
    monkeypatch.setattr(
        service_module,
        "all_providers",
        lambda settings: {
            "broken": FakeProvider(raise_error=True),
            "fake": FakeProvider([freelance_item("ok")]),
        },
    )
    search = FreelanceSearch(
        keywords="website",
        platforms=["broken", "fake"],
        include_demo=False,
        posted_within_days=None,
    )
    report = search_opportunities(db, settings, search, rules=FreelanceRules())
    assert report.found == 1
    assert "broken" in report.failed_providers
    assert any("Fake provider" in message for message in report.provider_messages)


def test_freelance_db_filters_and_stats(tmp_path):
    db = Database(tmp_path / "leads.db")
    first = freelance_item("a").to_dict()
    second = freelance_item("b", platform="Other", currency="USD", budget_max=500).to_dict()
    first["match_score"] = 80
    second["match_score"] = 20
    first["score_notes"] = "Great match"
    second["score_notes"] = "Weak match"
    db.upsert_freelance_opportunities([first, second])
    db.mark_new_freelance("")

    assert len(db.list_freelance(include_demo=False, min_score=50)) == 1
    assert len(db.list_freelance(include_demo=False, currency="USD")) == 1
    assert len(db.list_freelance(include_demo=False, platforms=["Fake"])) == 1
    assert len(db.list_freelance(include_demo=False, new_only=True)) == 2
    stats = db.freelance_stats()
    assert stats["total"] == 2
    assert stats["new"] == 2
