from datetime import date

from config import OPPORTUNITY_CLASSES, REVENUE_CATEGORIES, OpportunityRules
from mindsmiths.opportunity import score_opportunity
from mindsmiths.revenue import assess_revenue

TODAY = date(2026, 10, 23)


def social(**overrides):
    base = {
        "platform": "instagram",
        "url": "https://www.instagram.com/teststudio/",
        "followers": None,
        "followers_verified": False,
        "activity_verified": False,
        "last_active": None,
        "confidence": 0.9,
        "source": "website",
    }
    base.update(overrides)
    return base


def test_verified_revenue_is_only_presented_when_disclosed():
    assessment = assess_revenue({
        "name": "Anna Interiors",
        "verified_revenue": 5_000_000,
        "verified_revenue_source": "https://example.invalid/filing",
    })
    assert assessment.category == REVENUE_CATEGORIES[0]
    assert assessment.confidence == "high"
    assert assessment.revenue_range == (5_000_000, 5_000_000)
    assert "no additional revenue is inferred" in assessment.warning
    assert "https://example.invalid/filing" in assessment.sources


def test_third_party_estimate_is_not_presented_as_fact():
    assessment = assess_revenue({
        "name": "Anna Interiors",
        "third_party_revenue": 2_000_000,
        "third_party_revenue_source": "https://example.invalid/report",
    })
    assert assessment.category == REVENUE_CATEGORIES[1]
    assert assessment.confidence == "medium"
    assert "not a verified disclosure" in assessment.warning
    assert assessment.revenue_range == (2_000_000, 2_000_000)


def test_uncited_revenue_claims_are_not_treated_as_fact():
    verified = assess_revenue({"name": "Anna Interiors", "verified_revenue": 5_000_000})
    third_party = assess_revenue({"name": "Anna Interiors", "third_party_revenue": 2_000_000})
    for assessment in (verified, third_party):
        assert assessment.category == REVENUE_CATEGORIES[3]
        assert assessment.revenue_range is None
        assert assessment.band == "Unknown"
        assert "source" in assessment.warning.lower()


def test_review_counts_are_never_multiplied_into_revenue():
    assessment = assess_revenue({
        "name": "Anna Interiors",
        "review_count": 5000,
        "rating": 4.8,
    })
    assert assessment.category == REVENUE_CATEGORIES[2]
    assert assessment.revenue_range is None
    assert "not a revenue figure" in assessment.warning
    assert "never multiplied" in assessment.warning


def test_no_public_evidence_means_unknown_not_zero():
    assessment = assess_revenue({"name": "Anonymous"})
    assert assessment.category == REVENUE_CATEGORIES[3]
    assert assessment.band == "Unknown"
    assert assessment.affordability == "unknown"
    assert assessment.confidence == "low"
    assert assessment.revenue_range is None


def test_business_size_band_uses_public_signals_only():
    assessment = assess_revenue({
        "name": "Multi Branch Clinic",
        "number_of_locations": 5,
        "catalogue_size": 120,
        "review_count": 400,
        "rating": 4.6,
        "has_booking": True,
    })
    assert assessment.category == REVENUE_CATEGORIES[2]
    assert assessment.band == "Larger / multi-location"
    assert assessment.affordability == "higher-capability"
    assert any("public locations" in item for item in assessment.evidence)
    assert any("public reviews" in item for item in assessment.evidence)


def test_full_opportunity_signals_produce_high_confidence():
    record = {
        "name": "Multi Branch Clinic",
        "website": "",
        "website_status": "No website listed",
        "phone": "9876543210",
        "number_of_locations": 3,
        "catalogue_size": 30,
        "has_booking": True,
        "review_count": 100,
        "rating": 4.5,
        "expansion_signal": True,
        "socials": [social(
            followers=5000,
            followers_verified=True,
            activity_verified=True,
            last_active="2026-10-20",
        )],
    }
    result = score_opportunity(record, today=TODAY)
    assert result.score == 85
    assert result.classification == OPPORTUNITY_CLASSES[0]
    assert result.confidence == "high"
    assert result.budget_fit == "higher-capability"
    assert result.unknown == []
    assert result.recommended_offer
    assert result.next_action
    assert result.objections
    assert "not a statement" in result.why


def test_missing_evidence_stays_unknown_and_is_not_scored():
    result = score_opportunity({
        "name": "Bare Listing",
        "website": "",
        "website_status": "No website listed",
    }, today=TODAY)
    assert result.score == 20
    assert result.classification == OPPORTUNITY_CLASSES[2]
    assert result.confidence == "low"
    assert "Public business contact" in result.unknown
    assert "Recent verified activity" in result.unknown


def test_website_problem_only_scores_when_url_exists():
    result = score_opportunity({
        "name": "Broken Site",
        "website": "https://broken.invalid",
        "website_status": "Website unreachable",
    }, today=TODAY)
    assert result.score == 15
    signal = next(item for item in result.signals if item.name == "Website usability/functionality problem")
    assert signal.state == "positive"
    assert signal.points == 15


def test_stale_or_unverified_social_evidence_does_not_score():
    stale = score_opportunity({
        "name": "Stale Social",
        "website": "",
        "website_status": "No website listed",
        "phone": "9876543210",
        "socials": [social(
            followers=5000,
            followers_verified=True,
            activity_verified=True,
            last_active="2026-06-01",
        )],
    }, today=TODAY)
    unverified = score_opportunity({
        "name": "Unverified Social",
        "website": "",
        "website_status": "No website listed",
        "phone": "9876543210",
        "socials": [social(followers=50_000, followers_verified=False)],
    }, today=TODAY)
    assert stale.score == 35
    assert unverified.score == 25
    stale_activity = next(item for item in stale.signals if item.name == "Recent verified activity")
    assert stale_activity.state == "known"
    assert stale_activity.points == 0
    unverified_audience = next(item for item in unverified.signals if item.name == "Verified social audience")
    assert unverified_audience.state == "unknown"
    assert unverified_audience.points == 0


def test_custom_opportunity_weights_are_respected():
    result = score_opportunity(
        {"name": "Bare Listing", "website": "", "website_status": "No website listed"},
        rules=OpportunityRules(no_website=50, contact_available=0),
        today=TODAY,
    )
    assert result.score == 50
