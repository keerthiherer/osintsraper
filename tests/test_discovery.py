from config import get_settings
from mindsmiths.demo_data import load_sample_businesses
from mindsmiths.discovery import SearchParams, validate_search


def test_validation_requires_location_and_category():
    errors = validate_search(SearchParams(city="", category=""))
    assert any("City" in error for error in errors)
    assert any("category" in error.lower() for error in errors)


def test_validation_rejects_bad_result_limit():
    errors = validate_search(SearchParams(city="Chennai", category="Photographers", max_results=500))
    assert any("between 1 and 200" in error for error in errors)


def test_keyword_can_replace_category():
    errors = validate_search(SearchParams(city="Chennai", category="", keywords="wedding photographers"))
    assert errors == []


def test_sample_csv_loads_fictional_records():
    settings = get_settings()
    businesses = load_sample_businesses(settings.demo_csv)
    assert len(businesses) == 16
    assert all(business.source == "demo" for business in businesses)
    assert all(business.name for business in businesses)
    assert len({business.name for business in businesses}) == 16
    with_socials = [business for business in businesses if business.socials]
    assert len(with_socials) >= 10
    assert all(social.source == "demo" for business in with_socials for social in business.socials)
