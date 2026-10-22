from mindsmiths.db import Database
from mindsmiths.models import Business, SocialProfile


def make_db(tmp_path):
    return Database(tmp_path / "leads.db")


def test_duplicate_by_phone_merges_and_preserves_good_data(tmp_path):
    db = make_db(tmp_path)
    first = Business(
        name="Anna Lens Studio",
        city="Chennai",
        locality="Anna Nagar",
        phone="+91 90000 10001",
        email="hello@annalens.in",
        website="https://annalens.in",
        listing_url="https://maps.example/place/1",
        source="serpapi",
    )
    first_id, action = db.upsert_business(first)
    assert action == "new"

    second = Business(
        name="Anna Lens Studio",
        city="Chennai",
        locality="Anna Nagar",
        phone="9000010001",
        category="Photography studio",
        source="openstreetmap",
    )
    second_id, action = db.upsert_business(second)
    assert action == "updated"
    assert second_id == first_id

    rows = db.list_businesses()
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "hello@annalens.in"
    assert row["website"] == "https://annalens.in"
    assert row["listing_url"] == "https://maps.example/place/1"
    assert row["category"] == "Photography studio"


def test_duplicate_by_domain(tmp_path):
    db = make_db(tmp_path)
    db.upsert_business(Business(name="Studio One", city="Chennai", website="https://studiox.in"))
    _, action = db.upsert_business(
        Business(name="Studio One Photography", city="Chennai", website="http://www.studiox.in/about")
    )
    assert action == "updated"
    assert len(db.list_businesses()) == 1


def test_duplicate_by_listing_url_with_query(tmp_path):
    db = make_db(tmp_path)
    url = "https://www.google.com/maps/search/?api=1&query=Anna+Nagar+Lens+Studio"
    db.upsert_business(Business(name="Lens A", city="Chennai", listing_url=url))
    _, action = db.upsert_business(Business(name="Lens A", city="Chennai", listing_url=url))
    assert action == "updated"
    assert len(db.list_businesses()) == 1

    other = "https://www.google.com/maps/search/?api=1&query=Velachery+Interiors"
    db.upsert_business(Business(name="Interiors B", city="Chennai", listing_url=other))
    assert len(db.list_businesses()) == 2


def test_different_businesses_are_not_merged(tmp_path):
    db = make_db(tmp_path)
    db.upsert_business(Business(name="Studio One", city="Chennai", phone="9000010001"))
    db.upsert_business(Business(name="Studio Two", city="Chennai", phone="9000010002"))
    assert len(db.list_businesses()) == 2


def test_social_data_not_overwritten_by_empty_values(tmp_path):
    db = make_db(tmp_path)
    social = SocialProfile(
        platform="instagram",
        url="https://www.instagram.com/studiox/",
        followers=5000,
        followers_verified=True,
        activity_verified=True,
        last_active="2026-10-20",
        confidence=0.9,
        source="demo",
    )
    business = Business(
        name="Studio X", city="Chennai", phone="9000010001",
        socials=[social],
    )
    business_id, _ = db.upsert_business(business)
    db.upsert_business(Business(name="Studio X", city="Chennai", phone="9000010001"))
    saved = db.get_business(business_id)
    assert saved is not None
    assert len(saved["socials"]) == 1
    assert saved["socials"][0]["followers"] == 5000
    assert saved["socials"][0]["followers_verified"] is True


def test_records_persist_in_new_connection(tmp_path):
    db = make_db(tmp_path)
    db.upsert_business(Business(name="Persistent Studio", city="Chennai", phone="9000010001"))
    reopened = Database(tmp_path / "leads.db")
    rows = reopened.list_businesses()
    assert len(rows) == 1
    assert rows[0]["name"] == "Persistent Studio"
