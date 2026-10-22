from datetime import date

from config import ScoringRules
from mindsmiths.scoring import priority_for, score_business

TODAY = date(2026, 10, 22)


def record(**overrides):
    base = {
        "name": "Test Studio",
        "website": "",
        "website_status": "No website listed",
        "phone": "",
        "email": "",
        "rating": None,
        "review_count": None,
        "socials": [],
    }
    base.update(overrides)
    return base


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


def test_no_website_and_contact_points():
    result = score_business(record(phone="9876543210"), today=TODAY)
    assert result.score == 35
    assert any("No website" in note for note in result.notes)


def test_broken_website_only_scores_when_url_exists():
    broken = score_business(
        record(website="https://broken.invalid", website_status="Website unreachable"),
        today=TODAY,
    )
    check_failed = score_business(
        record(website="https://unknown.invalid", website_status="Website check failed"),
        today=TODAY,
    )
    assert broken.score == 20
    assert check_failed.score == 0


def test_unverified_or_small_audience_gets_no_follower_points():
    unverified = score_business(
        record(socials=[social(followers=50_000, followers_verified=False, source="openstreetmap")]),
        today=TODAY,
    )
    small = score_business(
        record(socials=[social(followers=1_999, followers_verified=True, source="openstreetmap")]),
        today=TODAY,
    )
    unknown = score_business(record(socials=[social(source="openstreetmap")]), today=TODAY)
    assert unverified.score == 30
    assert small.score == 30
    assert unknown.score == 30


def test_verified_active_social_adds_points_once():
    result = score_business(
        record(socials=[
            social(followers=5000, followers_verified=True, activity_verified=True, last_active="2026-10-01"),
            social(platform="facebook", url="https://facebook.com/test", followers=9000,
                   followers_verified=True, activity_verified=True, last_active="2026-10-02"),
        ]),
        today=TODAY,
    )
    assert result.score == 30 + 15 + 10 + 5
    assert sum("audience" in note for note in result.notes) == 1


def test_stale_activity_does_not_score():
    result = score_business(
        record(socials=[social(
            followers=5000, followers_verified=True,
            activity_verified=True, last_active="2026-08-01", source="openstreetmap",
        )]),
        today=TODAY,
    )
    assert result.score == 45


def test_reputation_requires_both_thresholds():
    high_rating_low_reviews = score_business(record(rating=4.9, review_count=19), today=TODAY)
    low_rating_high_reviews = score_business(record(rating=3.9, review_count=500), today=TODAY)
    good = score_business(record(rating=4.0, review_count=20), today=TODAY)
    assert high_rating_low_reviews.score == 30
    assert low_rating_high_reviews.score == 30
    assert good.score == 40


def test_strong_match_and_score_clamp():
    result = score_business(
        record(
            website="https://example.org",
            website_status="Website unreachable",
            phone="9876543210",
            email="hello@example.org",
            rating=4.8,
            review_count=100,
            socials=[social(
                followers=100_000, followers_verified=True,
                activity_verified=True, last_active="2026-10-21",
                confidence=0.95, source="website",
            )],
        ),
        today=TODAY,
    )
    assert result.score == 70
    assert result.priority == "Medium priority"

    clamped = score_business(
        record(
            phone="9876543210",
            email="a@b.in",
            rating=5.0,
            review_count=100,
            socials=[social(
                followers=10_000, followers_verified=True,
                activity_verified=True, last_active="2026-10-21",
            )],
        ),
        ScoringRules(
            no_website=60, verified_followers=60, recent_activity=60,
            phone=60, email=60, rating_reviews=60, strong_social_match=60,
        ),
        today=TODAY,
    )
    assert clamped.score == 100
    assert clamped.priority == "High priority"


def test_unknown_values_do_not_score():
    result = score_business(record(website_status="Unknown"), today=TODAY)
    assert result.score == 0
    assert result.priority == "Low priority"


def test_custom_rules_are_respected():
    rules = ScoringRules(no_website=50, phone=10, min_followers=1000)
    result = score_business(
        record(phone="9876543210", socials=[social(followers=1500, followers_verified=True, source="openstreetmap")]),
        rules,
        today=TODAY,
    )
    assert result.score == 50 + 10 + 15


def test_priority_boundaries():
    assert priority_for(80) == "High priority"
    assert priority_for(79) == "Medium priority"
    assert priority_for(60) == "Medium priority"
    assert priority_for(59) == "Low priority"


