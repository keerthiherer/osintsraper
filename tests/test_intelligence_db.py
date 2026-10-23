from mindsmiths.db import Database
from mindsmiths.models import Business


def make_db(tmp_path):
    return Database(tmp_path / "leads.db")


def test_intelligence_evidence_crm_and_outreach_roundtrip(tmp_path):
    db = make_db(tmp_path)
    business_id, _ = db.upsert_business(Business(
        name="Anna Interiors",
        city="Chennai",
        phone="9000010001",
        website="",
        website_status="No website listed",
        source="openstreetmap",
    ))

    db.update_opportunity(
        business_id,
        score=77,
        classification="High-priority opportunity",
        budget_fit="moderate",
        confidence="medium",
        notes="Strong public evidence.",
    )
    db.update_revenue(
        business_id,
        category="Estimated business-size category only",
        band="Small to medium business",
        confidence="medium",
        assessment_json='{"band": "Small to medium business"}',
    )
    db.update_audit(
        business_id,
        status="No website listed",
        report_json='{"status": "No website listed"}',
        error="",
    )
    db.update_business_fields(business_id, {
        "number_of_locations": 2,
        "catalogue_size": 30,
        "services_summary": "Residential and commercial interiors",
        "has_booking": True,
        "website_status": "Website reachable",
    })
    db.update_crm(business_id, {
        "status": "Quotation sent",
        "follow_up_date": "2026-10-30",
        "quoted_amount": 50_000,
        "client_budget": 45_000,
        "objections": "Wants a smaller first phase.",
        "last_contact_date": "2026-10-23",
        "lead_source": "OpenStreetMap",
        "won_lost_reason": "",
    })
    db.add_activity(business_id, "Called the owner.", "contact")
    db.add_activity(business_id, "Sent the quotation.", "quotation")
    db.save_outreach_draft(
        business_id,
        channel="Email",
        tone="Professional",
        offer="Business website",
        subject="Website for Anna Interiors",
        body="Draft body",
        approved=True,
    )

    saved = db.get_business(business_id)
    assert saved is not None
    assert saved["opportunity_score"] == 77
    assert saved["opportunity_class"] == "High-priority opportunity"
    assert saved["budget_fit"] == "moderate"
    assert saved["revenue_band"] == "Small to medium business"
    assert saved["audit_report"] == '{"status": "No website listed"}'
    assert saved["number_of_locations"] == 2
    assert saved["has_booking"] == 1
    assert saved["website_status"] == "Website reachable"
    assert saved["status"] == "Quotation sent"
    assert saved["quoted_amount"] == 50_000
    assert saved["follow_up_date"] == "2026-10-30"

    activities = db.list_activities(business_id)
    assert [item["activity_type"] for item in activities] == ["quotation", "contact"]
    drafts = db.list_outreach_drafts(business_id)
    assert len(drafts) == 1
    assert drafts[0]["approved"] == 1

    db.record_evidence(
        business_id, "phone", "9000010001",
        source_url="https://example.invalid/listing",
        state="verified", confidence="high", reason="Public listing",
    )
    db.record_evidence(
        business_id, "phone", "9000010001",
        source_url="https://example.invalid/listing",
        state="verified", confidence="high", reason="Rechecked",
    )
    evidence = db.evidence_for(business_id)
    assert len(evidence) == 1
    assert evidence[0]["reason"] == "Rechecked"
    summary = db.evidence_summary()
    assert summary["fields"] == 1
    assert summary["businesses"] == 1
    assert summary["verified"] == 1

    metrics = db.crm_metrics()
    assert metrics["total"] == 1
    assert metrics["qualified"] == 1
    assert metrics["contacted"] == 1
    assert metrics["replied"] == 1
    assert metrics["quotations_sent"] == 1
    assert metrics["total_quoted"] == 50_000
    assert metrics["reply_rate"] == 100.0
    assert metrics["conversion_rate"] == 0.0
    assert metrics["sample_warning"]

    backup = db.backup(tmp_path / "backups")
    assert (tmp_path / "backups").exists()
    assert backup.endswith(".db")


def test_duplicate_review_and_conservative_merge(tmp_path):
    db = make_db(tmp_path)
    keep_id, _ = db.upsert_business(Business(name="Keep Interiors", city="Chennai", phone="9000010001"))
    merge_id, _ = db.upsert_business(Business(name="Merge Interiors", city="Chennai", phone="9000010002"))
    with db.connect() as conn:
        conn.execute(
            "UPDATE businesses SET phone_norm = 'shared_number', email = ? WHERE id = ?",
            ("merged@example.invalid", merge_id),
        )
        conn.execute(
            "UPDATE businesses SET phone_norm = 'shared_number' WHERE id = ?",
            (keep_id,),
        )
    groups = db.duplicate_candidates()
    assert any(group["n"] >= 2 for group in groups)

    db.add_activity(merge_id, "Moved activity.", "note")
    assert db.merge_businesses(keep_id, merge_id) is True
    assert db.get_business(merge_id) is None
    kept = db.get_business(keep_id)
    assert kept is not None
    assert kept["email"] == "merged@example.invalid"
    assert any(item["note"] == "Moved activity." for item in db.list_activities(keep_id))


def test_migration_adds_new_columns_to_existing_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            listing_url TEXT DEFAULT '',
            domain TEXT DEFAULT '',
            phone_norm TEXT DEFAULT '',
            identity_key TEXT DEFAULT '',
            website TEXT DEFAULT '',
            website_status TEXT DEFAULT 'Unknown',
            last_seen_at TEXT DEFAULT '',
            collected_at TEXT DEFAULT '',
            score INTEGER DEFAULT 0
        )"""
    )
    conn.execute("INSERT INTO businesses (name) VALUES ('Old Record')")
    conn.commit()
    conn.close()

    db = Database(path)
    with db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(businesses)")}
        names = [row["name"] for row in conn.execute("SELECT name FROM businesses")]
    assert "verified_revenue" in columns
    assert "opportunity_score" in columns
    assert "audit_report" in columns
    assert names == ["Old Record"]
