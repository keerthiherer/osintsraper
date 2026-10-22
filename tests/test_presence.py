from config import get_settings
from mindsmiths.contacts import is_business_email
from mindsmiths.models import Business, normalize_phone
from mindsmiths.presence import (
    PHONE_RE,
    SearchResult,
    WebSearchClient,
    _extract_socials,
    _parse_followers,
    _website_candidate,
)


def test_website_candidate_rejects_directory_listing():
    business = Business(name="Puja Digital Studio", city="Chennai")
    results = [
        SearchResult(
            title="Puja Digital Studio - WorldPlaces",
            url="https://india.worldplaces.me/view-place/72156073-puja-digital-studio.html",
            snippet="Puja Digital Studio Chennai photographer",
        )
    ]
    assert _website_candidate(results, business) == ""


def test_website_candidate_rejects_same_name_site_without_city_evidence():
    business = Business(name="GK Photography", city="Chennai", locality="Sithalapakkam")
    results = [
        SearchResult(
            title="Gk Photography",
            url="https://gkphotographykpt.com/",
            snippet="Gk Photography offers wedding and event photography.",
        )
    ]
    assert _website_candidate(results, business) == ""


def test_website_candidate_accepts_exact_brand_domain():
    business = Business(name="Puja Digital Studio", city="Chennai")
    results = [
        SearchResult(
            title="Puja Digital Studio",
            url="https://pujadigitalstudio.com/",
            snippet="Puja Digital Studio photography services.",
        )
    ]
    assert _website_candidate(results, business) == "https://pujadigitalstudio.com/"


def test_socials_require_location_or_exact_handle():
    business = Business(name="Puja Digital Studio", city="Chennai")
    wrong_city = [
        SearchResult(
            title="Puja Digital Studio (@puja_digital_dhn)",
            url="https://www.instagram.com/puja_digital_dhn/",
            snippet="120 Followers, 300 Following",
        )
    ]
    assert _extract_socials(wrong_city, business) == []

    exact_handle = [
        SearchResult(
            title="GK Photography (@_gk_photography____)",
            url="https://www.instagram.com/_gk_photography____/",
            snippet="249 Followers, 552 Following",
        )
    ]
    socials = _extract_socials(exact_handle, Business(name="GK Photography", city="Chennai"))
    assert len(socials) == 1
    assert socials[0].followers == 249
    assert socials[0].followers_verified is False


def test_followers_parse_suffixes_and_ignore_likes():
    assert _parse_followers("749K Followers, 306 Following") == 749000
    assert _parse_followers("2,315 likes, 33 comments") is None


def test_phone_regex_ignores_facebook_numeric_ids():
    assert PHONE_RE.search("www.facebook.com/100079397380763/") is None
    match = PHONE_RE.search("For bookings: +91 9840 76 7566")
    assert match is not None
    assert normalize_phone(match.group(0)) == "9840767566"


def test_placeholder_contact_values_are_rejected():
    assert normalize_phone("+91700834570") == ""
    assert normalize_phone("+91 9840 76 7566") == "9840767566"
    assert is_business_email("filler@godaddy.com") is False
    assert is_business_email("leads@zggroup.in") is True


def test_reader_markdown_parses_results():
    client = WebSearchClient(get_settings())
    markdown = """Title: example

## [GK Photography - Facebook](https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.facebook.com%2F100079397380763%2F&rut=x)

[www.facebook.com/100079397380763/](https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.facebook.com%2F100079397380763%2F&rut=x)

Gk Photography, Chennai. 42 likes. Photography services.

## [GK Photography (@_gk_photography____)](https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.instagram.com%2F_gk_photography____%2F&rut=y)

249 Followers, 552 Following, 57 Posts.
"""
    results = client._parse_reader_markdown(markdown)
    assert len(results) == 2
    assert results[0].url == "https://www.facebook.com/100079397380763/"
    assert "Chennai" in results[0].snippet
    assert results[1].url == "https://www.instagram.com/_gk_photography____/"
