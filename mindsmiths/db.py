"""SQLite persistence with conservative merge and deduplication."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    Business,
    SocialProfile,
    domain_from_url,
    identity_key,
    normalize_phone,
    normalize_url,
    now_iso,
)

BUSINESS_COLUMNS = [
    "name", "category", "address", "city", "locality", "phone", "email",
    "website", "listing_url", "rating", "review_count", "opening_hours",
    "source", "collected_at", "last_seen_at", "search_query",
    "website_status", "website_http_status", "website_final_url",
    "website_title", "website_issues", "contact_page", "form_url",
    "website_source", "phone_source", "email_source",
    "notes", "status", "excluded", "identity_key", "domain", "phone_norm",
    "number_of_locations", "catalogue_size", "product_price_min",
    "product_price_max", "services_summary", "has_booking", "has_enquiry",
    "promotes_services", "expansion_signal", "established_signal",
    "website_response_ms", "website_page_bytes", "has_cta",
    "verified_revenue", "verified_revenue_source", "third_party_revenue",
    "third_party_revenue_source",
]

SOCIAL_COLUMNS = [
    "platform", "url", "followers", "followers_verified", "activity_verified",
    "last_active", "confidence", "source", "collected_at",
]

# Columns added after the original schema. All are nullable or have defaults so
# the migration is safe for existing databases.
MIGRATION_COLUMNS: dict[str, str] = {
    "website_source": "TEXT DEFAULT ''",
    "phone_source": "TEXT DEFAULT ''",
    "email_source": "TEXT DEFAULT ''",
    "number_of_locations": "INTEGER",
    "catalogue_size": "INTEGER",
    "product_price_min": "REAL",
    "product_price_max": "REAL",
    "services_summary": "TEXT DEFAULT ''",
    "has_booking": "INTEGER",
    "has_enquiry": "INTEGER",
    "promotes_services": "INTEGER",
    "expansion_signal": "INTEGER",
    "established_signal": "INTEGER",
    "website_response_ms": "INTEGER",
    "website_page_bytes": "INTEGER",
    "has_cta": "INTEGER",
    "verified_revenue": "REAL",
    "verified_revenue_source": "TEXT DEFAULT ''",
    "third_party_revenue": "REAL",
    "third_party_revenue_source": "TEXT DEFAULT ''",
    "audit_report": "TEXT DEFAULT ''",
    "audit_checked_at": "TEXT DEFAULT ''",
    "revenue_category": "TEXT DEFAULT ''",
    "revenue_band": "TEXT DEFAULT ''",
    "revenue_confidence": "TEXT DEFAULT ''",
    "revenue_assessment": "TEXT DEFAULT ''",
    "revenue_updated_at": "TEXT DEFAULT ''",
    "opportunity_score": "INTEGER DEFAULT 0",
    "opportunity_class": "TEXT DEFAULT 'Needs more research'",
    "budget_fit": "TEXT DEFAULT ''",
    "opportunity_confidence": "TEXT DEFAULT ''",
    "opportunity_notes": "TEXT DEFAULT ''",
    "opportunity_updated_at": "TEXT DEFAULT ''",
    "follow_up_date": "TEXT DEFAULT ''",
    "proposed_quotation": "REAL",
    "quoted_amount": "REAL",
    "client_budget": "REAL",
    "objections": "TEXT DEFAULT ''",
    "last_contact_date": "TEXT DEFAULT ''",
    "lead_source": "TEXT DEFAULT ''",
    "won_lost_reason": "TEXT DEFAULT ''",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT '',
    address TEXT DEFAULT '',
    city TEXT DEFAULT '',
    locality TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    website TEXT DEFAULT '',
    listing_url TEXT DEFAULT '',
    rating REAL,
    review_count INTEGER,
    opening_hours TEXT DEFAULT '',
    source TEXT DEFAULT '',
    collected_at TEXT DEFAULT '',
    last_seen_at TEXT DEFAULT '',
    search_query TEXT DEFAULT '',
    website_status TEXT DEFAULT 'Unknown',
    website_http_status INTEGER,
    website_final_url TEXT DEFAULT '',
    website_title TEXT DEFAULT '',
    website_issues TEXT DEFAULT '',
    contact_page TEXT DEFAULT '',
    form_url TEXT DEFAULT '',
    website_source TEXT DEFAULT '',
    phone_source TEXT DEFAULT '',
    email_source TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    excluded INTEGER DEFAULT 0,
    identity_key TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    phone_norm TEXT DEFAULT '',
    number_of_locations INTEGER,
    catalogue_size INTEGER,
    product_price_min REAL,
    product_price_max REAL,
    services_summary TEXT DEFAULT '',
    has_booking INTEGER,
    has_enquiry INTEGER,
    promotes_services INTEGER,
    expansion_signal INTEGER,
    established_signal INTEGER,
    website_response_ms INTEGER,
    website_page_bytes INTEGER,
    has_cta INTEGER,
    verified_revenue REAL,
    verified_revenue_source TEXT DEFAULT '',
    third_party_revenue REAL,
    third_party_revenue_source TEXT DEFAULT '',
    audit_report TEXT DEFAULT '',
    audit_checked_at TEXT DEFAULT '',
    revenue_category TEXT DEFAULT '',
    revenue_band TEXT DEFAULT '',
    revenue_confidence TEXT DEFAULT '',
    revenue_assessment TEXT DEFAULT '',
    revenue_updated_at TEXT DEFAULT '',
    opportunity_score INTEGER DEFAULT 0,
    opportunity_class TEXT DEFAULT 'Needs more research',
    budget_fit TEXT DEFAULT '',
    opportunity_confidence TEXT DEFAULT '',
    opportunity_notes TEXT DEFAULT '',
    opportunity_updated_at TEXT DEFAULT '',
    follow_up_date TEXT DEFAULT '',
    proposed_quotation REAL,
    quoted_amount REAL,
    client_budget REAL,
    objections TEXT DEFAULT '',
    last_contact_date TEXT DEFAULT '',
    lead_source TEXT DEFAULT '',
    won_lost_reason TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    priority TEXT DEFAULT 'Low priority',
    qualification_notes TEXT DEFAULT '',
    score_updated_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_businesses_listing ON businesses(listing_url);
CREATE INDEX IF NOT EXISTS idx_businesses_domain ON businesses(domain);
CREATE INDEX IF NOT EXISTS idx_businesses_phone ON businesses(phone_norm);
CREATE INDEX IF NOT EXISTS idx_businesses_identity ON businesses(identity_key);
CREATE INDEX IF NOT EXISTS idx_businesses_score ON businesses(score);

CREATE TABLE IF NOT EXISTS social_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    url TEXT NOT NULL,
    followers INTEGER,
    followers_verified INTEGER DEFAULT 0,
    activity_verified INTEGER DEFAULT 0,
    last_active TEXT,
    confidence REAL DEFAULT 0,
    source TEXT DEFAULT '',
    collected_at TEXT DEFAULT '',
    UNIQUE(business_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_social_business ON social_profiles(business_id);

CREATE TABLE IF NOT EXISTS data_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    value TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    collected_at TEXT DEFAULT '',
    last_checked_at TEXT DEFAULT '',
    state TEXT DEFAULT 'unverified',
    confidence TEXT DEFAULT 'low',
    reason TEXT DEFAULT '',
    UNIQUE(business_id, field_name, source_url)
);
CREATE INDEX IF NOT EXISTS idx_evidence_business ON data_evidence(business_id);

CREATE TABLE IF NOT EXISTS crm_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    activity_type TEXT DEFAULT 'note',
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activities_business ON crm_activities(business_id);

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    channel TEXT DEFAULT '',
    tone TEXT DEFAULT '',
    offer TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    body TEXT DEFAULT '',
    approved INTEGER DEFAULT 0,
    created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_outreach_business ON outreach_drafts(business_id);

CREATE TABLE IF NOT EXISTS website_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    checked_at TEXT DEFAULT '',
    status TEXT DEFAULT '',
    report_json TEXT DEFAULT '',
    error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audits_business ON website_audits(business_id);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS freelance_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT UNIQUE,
    platform TEXT DEFAULT '',
    external_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    url TEXT DEFAULT '',
    posted_at TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    budget_min REAL,
    budget_max REAL,
    budget_type TEXT DEFAULT '',
    currency TEXT DEFAULT '',
    skills TEXT DEFAULT '',
    experience TEXT DEFAULT '',
    client_info TEXT DEFAULT '',
    proposal_count INTEGER,
    project_status TEXT DEFAULT 'Possibly open; status unconfirmed',
    status_verified INTEGER DEFAULT 0,
    last_checked_at TEXT DEFAULT '',
    first_seen_at TEXT DEFAULT '',
    last_seen_at TEXT DEFAULT '',
    is_new INTEGER DEFAULT 0,
    match_score INTEGER DEFAULT 0,
    score_notes TEXT DEFAULT '',
    source_query TEXT DEFAULT '',
    is_demo INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_freelance_platform ON freelance_opportunities(platform);
CREATE INDEX IF NOT EXISTS idx_freelance_score ON freelance_opportunities(match_score);
CREATE INDEX IF NOT EXISTS idx_freelance_new ON freelance_opportunities(is_new);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(businesses)")}
            for column, definition in MIGRATION_COLUMNS.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE businesses ADD COLUMN {column} {definition}")

    def find_duplicate(self, conn: sqlite3.Connection, data: dict[str, Any]) -> sqlite3.Row | None:
        clauses, params = [], []
        for column in ("listing_url", "phone_norm", "domain", "identity_key"):
            value = data.get(column) or ""
            if value:
                clauses.append(f"({column} != '' AND {column} = ?)")
                params.append(value)
        if not clauses:
            return None
        sql = f"SELECT * FROM businesses WHERE {' OR '.join(clauses)} ORDER BY last_seen_at DESC LIMIT 1"
        return conn.execute(sql, params).fetchone()

    def upsert_business(self, business: Business) -> tuple[int, str]:
        """Insert or conservatively merge a business. Returns (id, 'new'|'updated')."""
        business.finalize()
        data = business.to_dict()
        data["last_seen_at"] = now_iso()
        with self.connect() as conn:
            existing = self.find_duplicate(conn, data)
            if existing is None:
                data["score"] = 0
                data["priority"] = "Low priority"
                data["qualification_notes"] = ""
                data["score_updated_at"] = ""
                columns = list(data.keys())
                placeholders = ", ".join("?" for _ in columns)
                sql = f"INSERT INTO businesses ({', '.join(columns)}) VALUES ({placeholders})"
                cur = conn.execute(sql, [data[c] for c in columns])
                business_id = int(cur.lastrowid)
                action = "new"
            else:
                business_id = int(existing["id"])
                merged = dict(existing)
                for column in BUSINESS_COLUMNS:
                    incoming = data.get(column)
                    if column in {"collected_at", "last_seen_at", "identity_key", "domain", "phone_norm"}:
                        continue
                    if column in {"rating", "review_count"}:
                        if incoming is not None:
                            merged[column] = incoming
                    elif column == "website_status":
                        # Preserve existing website evidence when the new source has no website.
                        if data.get("website") or not existing["website"]:
                            merged[column] = incoming
                    elif column in {"website_http_status", "website_final_url", "website_title", "website_issues"}:
                        if data.get("website") or not existing["website"]:
                            merged[column] = incoming
                    elif incoming not in (None, ""):
                        merged[column] = incoming

                merged["identity_key"] = identity_key(
                    merged["name"], merged["city"], merged["locality"]
                )
                merged["domain"] = domain_from_url(merged["website"])
                merged["phone_norm"] = normalize_phone(merged["phone"])
                merged["last_seen_at"] = data["last_seen_at"]
                if not merged.get("collected_at"):
                    merged["collected_at"] = data["collected_at"]

                columns = [c for c in BUSINESS_COLUMNS if c not in {"identity_key", "domain", "phone_norm"}]
                set_clause = ", ".join(f"{c} = ?" for c in columns)
                conn.execute(
                    f"UPDATE businesses SET {set_clause}, identity_key = ?, domain = ?, phone_norm = ? WHERE id = ?",
                    [merged[c] for c in columns]
                    + [merged["identity_key"], merged["domain"], merged["phone_norm"], business_id],
                )
                action = "updated"

            for social in business.socials:
                if social.url:
                    self._upsert_social(conn, business_id, social)
        return business_id, action

    def _upsert_social(self, conn: sqlite3.Connection, business_id: int, social: SocialProfile) -> None:
        existing = conn.execute(
            "SELECT * FROM social_profiles WHERE business_id = ? AND platform = ?",
            (business_id, social.platform),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO social_profiles
                   (business_id, platform, url, followers, followers_verified, activity_verified,
                    last_active, confidence, source, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    business_id, social.platform, normalize_url(social.url), social.followers,
                    int(social.followers_verified), int(social.activity_verified),
                    social.last_active, social.confidence, social.source,
                    social.collected_at or now_iso(),
                ),
            )
            return

        followers = existing["followers"]
        followers_verified = bool(existing["followers_verified"])
        if social.followers is not None and (
            social.followers_verified or not followers_verified
        ):
            followers = social.followers
            followers_verified = social.followers_verified

        last_active = existing["last_active"]
        activity_verified = bool(existing["activity_verified"])
        if social.last_active and (social.activity_verified or not activity_verified):
            last_active = social.last_active
            activity_verified = social.activity_verified

        conn.execute(
            """UPDATE social_profiles SET
               url = COALESCE(NULLIF(?, ''), url),
               followers = ?, followers_verified = ?, activity_verified = ?,
               last_active = ?, confidence = MAX(confidence, ?),
               source = CASE WHEN ? != '' THEN ? ELSE source END,
               collected_at = CASE WHEN ? != '' THEN ? ELSE collected_at END
               WHERE id = ?""",
            (
                normalize_url(social.url), followers, int(followers_verified),
                int(activity_verified), last_active, social.confidence,
                social.source, social.source, social.collected_at, social.collected_at,
                existing["id"],
            ),
        )

    def _socials_for(self, conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT platform, url, followers, followers_verified, activity_verified, "
            "last_active, confidence, source, collected_at "
            "FROM social_profiles WHERE business_id = ? ORDER BY platform",
            (business_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["followers_verified"] = bool(item["followers_verified"])
            item["activity_verified"] = bool(item["activity_verified"])
            result.append(item)
        return result

    def get_business(self, business_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["excluded"] = bool(item["excluded"])
            item["socials"] = self._socials_for(conn, business_id)
            return item

    def list_businesses(
        self,
        *,
        search: str = "",
        website_statuses: list[str] | None = None,
        min_followers: int | None = None,
        active_days: int | None = None,
        phone_only: bool = False,
        email_only: bool = False,
        high_priority_only: bool = False,
        no_website_only: bool = False,
        broken_only: bool = False,
        include_excluded: bool = False,
        statuses: list[str] | None = None,
        cities: list[str] | None = None,
        categories: list[str] | None = None,
        budget_fits: list[str] | None = None,
        opportunity_classes: list[str] | None = None,
        min_opportunity_score: int | None = None,
        follow_up_before: str | None = None,
        follow_up_only: bool = False,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if not include_excluded:
            where.append("b.excluded = 0")
        if search:
            like = f"%{search.strip()}%"
            where.append("(b.name LIKE ? OR b.category LIKE ? OR b.city LIKE ? OR b.locality LIKE ? OR b.phone LIKE ? OR b.email LIKE ?)")
            params.extend([like] * 6)
        if website_statuses:
            placeholders = ", ".join("?" for _ in website_statuses)
            where.append(f"b.website_status IN ({placeholders})")
            params.extend(website_statuses)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            where.append(f"b.status IN ({placeholders})")
            params.extend(statuses)
        if cities:
            placeholders = ", ".join("?" for _ in cities)
            where.append(f"b.city IN ({placeholders})")
            params.extend(cities)
        if categories:
            placeholders = ", ".join("?" for _ in categories)
            where.append(f"b.category IN ({placeholders})")
            params.extend(categories)
        if budget_fits:
            placeholders = ", ".join("?" for _ in budget_fits)
            where.append(f"b.budget_fit IN ({placeholders})")
            params.extend(budget_fits)
        if opportunity_classes:
            placeholders = ", ".join("?" for _ in opportunity_classes)
            where.append(f"b.opportunity_class IN ({placeholders})")
            params.extend(opportunity_classes)
        if min_opportunity_score is not None:
            where.append("b.opportunity_score >= ?")
            params.append(int(min_opportunity_score))
        if follow_up_before:
            where.append("b.follow_up_date != '' AND substr(b.follow_up_date, 1, 10) <= ?")
            params.append(str(follow_up_before)[:10])
        if follow_up_only:
            where.append("b.follow_up_date != ''")
        if no_website_only:
            where.append("b.website_status = 'No website listed'")
        if broken_only:
            where.append("b.website_status IN ('Website unreachable', 'Website check failed')")
        if phone_only:
            where.append("b.phone != ''")
        if email_only:
            where.append("b.email != ''")
        if high_priority_only:
            where.append("b.score >= 80")
        if min_followers is not None:
            where.append(
                "EXISTS (SELECT 1 FROM social_profiles s WHERE s.business_id = b.id "
                "AND s.followers_verified = 1 AND s.followers >= ?)"
            )
            params.append(min_followers)
        if active_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(active_days))).date().isoformat()
            where.append(
                "EXISTS (SELECT 1 FROM social_profiles s WHERE s.business_id = b.id "
                "AND s.activity_verified = 1 AND substr(s.last_active, 1, 10) >= ?)"
            )
            params.append(cutoff)

        sql = "SELECT b.* FROM businesses b"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += (
            " ORDER BY CASE WHEN b.website_status = 'No website listed' THEN 0"
            " WHEN b.website_status = 'Website unreachable' THEN 1 ELSE 2 END,"
            " b.score DESC, b.name COLLATE NOCASE ASC LIMIT ?"
        )
        params.append(int(limit))

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["excluded"] = bool(item["excluded"])
                item["socials"] = self._socials_for(conn, item["id"])
                results.append(item)
            return results

    def update_score(self, business_id: int, score: int, priority: str, notes: list[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE businesses SET score = ?, priority = ?, qualification_notes = ?, score_updated_at = ? WHERE id = ?",
                (score, priority, "; ".join(notes), now_iso(), business_id),
            )

    def update_status(self, business_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE businesses SET status = ? WHERE id = ?", (status, business_id))

    def update_notes(self, business_id: int, notes: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE businesses SET notes = ? WHERE id = ?", (notes, business_id))

    def set_excluded(self, business_id: int, excluded: bool) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE businesses SET excluded = ? WHERE id = ?", (int(excluded), business_id))

    # ------------------------------------------------------------------
    # Intelligence, audit, CRM, evidence and outreach
    # ------------------------------------------------------------------
    def update_opportunity(
        self,
        business_id: int,
        *,
        score: int,
        classification: str,
        budget_fit: str,
        confidence: str,
        notes: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE businesses SET opportunity_score = ?, opportunity_class = ?,
                   budget_fit = ?, opportunity_confidence = ?, opportunity_notes = ?,
                   opportunity_updated_at = ? WHERE id = ?""",
                (int(score), classification, budget_fit, confidence, notes, now_iso(), business_id),
            )

    def update_revenue(
        self,
        business_id: int,
        *,
        category: str,
        band: str,
        confidence: str,
        assessment_json: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE businesses SET revenue_category = ?, revenue_band = ?,
                   revenue_confidence = ?, revenue_assessment = ?,
                   revenue_updated_at = ? WHERE id = ?""",
                (category, band, confidence, assessment_json, now_iso(), business_id),
            )

    def update_audit(self, business_id: int, *, status: str, report_json: str, error: str = "") -> None:
        checked_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                """UPDATE businesses SET audit_report = ?, audit_checked_at = ? WHERE id = ?""",
                (report_json, checked_at, business_id),
            )
            conn.execute(
                """INSERT INTO website_audits (business_id, checked_at, status, report_json, error)
                   VALUES (?, ?, ?, ?, ?)""",
                (business_id, checked_at, status, report_json, error),
            )

    def update_business_fields(self, business_id: int, fields: dict[str, Any]) -> None:
        allowed = {
            "number_of_locations", "catalogue_size", "product_price_min",
            "product_price_max", "services_summary", "has_booking", "has_enquiry",
            "promotes_services", "expansion_signal", "established_signal",
            "verified_revenue", "verified_revenue_source", "third_party_revenue",
            "third_party_revenue_source", "notes", "status", "excluded",
            "website_status", "website_response_ms", "website_page_bytes", "has_cta",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return
        set_clause = ", ".join(f"{key} = ?" for key in clean)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE businesses SET {set_clause} WHERE id = ?",
                list(clean.values()) + [business_id],
            )

    def update_crm(self, business_id: int, fields: dict[str, Any]) -> None:
        allowed = {
            "status", "follow_up_date", "proposed_quotation", "quoted_amount",
            "client_budget", "objections", "last_contact_date", "lead_source",
            "won_lost_reason", "notes",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return
        set_clause = ", ".join(f"{key} = ?" for key in clean)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE businesses SET {set_clause} WHERE id = ?",
                list(clean.values()) + [business_id],
            )

    def add_activity(self, business_id: int, note: str, activity_type: str = "note") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO crm_activities (business_id, activity_type, note, created_at) VALUES (?, ?, ?, ?)",
                (business_id, activity_type, note.strip(), now_iso()),
            )

    def list_activities(self, business_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM crm_activities WHERE business_id = ? ORDER BY id DESC LIMIT ?",
                (business_id, int(limit)),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_outreach_draft(
        self,
        business_id: int,
        *,
        channel: str,
        tone: str,
        offer: str,
        subject: str,
        body: str,
        approved: bool = False,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO outreach_drafts
                   (business_id, channel, tone, offer, subject, body, approved, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (business_id, channel, tone, offer, subject, body, int(approved), now_iso()),
            )
            return int(cur.lastrowid)

    def list_outreach_drafts(self, business_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outreach_drafts WHERE business_id = ? ORDER BY id DESC LIMIT ?",
                (business_id, int(limit)),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_evidence(
        self,
        business_id: int,
        field_name: str,
        value: Any,
        *,
        source_url: str = "",
        state: str = "unverified",
        confidence: str = "low",
        reason: str = "",
    ) -> None:
        if value in (None, ""):
            return
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO data_evidence
                   (business_id, field_name, value, source_url, collected_at,
                    last_checked_at, state, confidence, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(business_id, field_name, source_url) DO UPDATE SET
                     value = excluded.value,
                     last_checked_at = excluded.last_checked_at,
                     state = excluded.state,
                     confidence = excluded.confidence,
                     reason = excluded.reason""",
                (
                    business_id, field_name, str(value), source_url, now_iso(), now_iso(),
                    state, confidence, reason,
                ),
            )

    def evidence_for(self, business_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM data_evidence WHERE business_id = ? ORDER BY field_name, id",
                (business_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def evidence_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS fields, COUNT(DISTINCT business_id) AS businesses,
                          SUM(CASE WHEN state = 'verified' THEN 1 ELSE 0 END) AS verified,
                          SUM(CASE WHEN state = 'unavailable' THEN 1 ELSE 0 END) AS unavailable
                   FROM data_evidence"""
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                   updated_at = excluded.updated_at""",
                (key, value, now_iso()),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def crm_metrics(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status NOT IN ('New lead', '') THEN 1 ELSE 0 END) AS qualified,
                          SUM(CASE WHEN status IN ('Contacted','Replied','Meeting scheduled','Quotation sent','Negotiation','Won','Lost','Follow-up required') THEN 1 ELSE 0 END) AS contacted,
                          SUM(CASE WHEN status IN ('Replied','Meeting scheduled','Quotation sent','Negotiation','Won') THEN 1 ELSE 0 END) AS replied,
                          SUM(CASE WHEN status IN ('Quotation sent','Negotiation','Won') THEN 1 ELSE 0 END) AS quotations_sent,
                          SUM(CASE WHEN status = 'Won' THEN 1 ELSE 0 END) AS won,
                          SUM(CASE WHEN status = 'Lost' THEN 1 ELSE 0 END) AS lost,
                          COALESCE(SUM(quoted_amount), 0) AS total_quoted,
                          COALESCE(SUM(CASE WHEN status = 'Won' THEN quoted_amount ELSE 0 END), 0) AS won_value
                   FROM businesses WHERE excluded = 0"""
            ).fetchone()
            data = dict(row)
        contacted = int(data.get("contacted") or 0)
        replied = int(data.get("replied") or 0)
        qualified = int(data.get("qualified") or 0)
        won = int(data.get("won") or 0)
        data["reply_rate"] = round(replied / contacted * 100, 1) if contacted else None
        data["conversion_rate"] = round(won / qualified * 100, 1) if qualified else None
        data["sample_warning"] = (
            "Sample size is small (fewer than 10 contacted leads); treat rates as indicative only."
            if contacted < 10 else ""
        )
        return data

    def duplicate_candidates(self) -> list[dict[str, Any]]:
        """Groups sharing a non-empty phone/domain, for manual review."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT domain, phone_norm, COUNT(*) AS n,
                          GROUP_CONCAT(id) AS ids, GROUP_CONCAT(name, ' | ') AS names
                   FROM businesses WHERE excluded = 0
                   AND (domain != '' OR phone_norm != '')
                   GROUP BY CASE WHEN domain != '' THEN 'd:' || domain ELSE 'p:' || phone_norm END
                   HAVING COUNT(*) > 1"""
            ).fetchall()
            return [dict(row) for row in rows]

    def merge_businesses(self, keep_id: int, merge_id: int) -> bool:
        if keep_id == merge_id:
            return False
        with self.connect() as conn:
            keep = conn.execute("SELECT * FROM businesses WHERE id = ?", (keep_id,)).fetchone()
            merge = conn.execute("SELECT * FROM businesses WHERE id = ?", (merge_id,)).fetchone()
            if keep is None or merge is None:
                return False
            updates = {}
            for column in BUSINESS_COLUMNS:
                if column in {"name", "identity_key", "domain", "phone_norm"}:
                    continue
                if keep[column] in (None, "") and merge[column] not in (None, ""):
                    updates[column] = merge[column]
            if updates:
                set_clause = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE businesses SET {set_clause} WHERE id = ?",
                    list(updates.values()) + [keep_id],
                )
            conn.execute(
                "UPDATE OR IGNORE social_profiles SET business_id = ? WHERE business_id = ?",
                (keep_id, merge_id),
            )
            conn.execute(
                "UPDATE OR IGNORE data_evidence SET business_id = ? WHERE business_id = ?",
                (keep_id, merge_id),
            )
            conn.execute(
                "UPDATE crm_activities SET business_id = ? WHERE business_id = ?",
                (keep_id, merge_id),
            )
            conn.execute(
                "UPDATE outreach_drafts SET business_id = ? WHERE business_id = ?",
                (keep_id, merge_id),
            )
            conn.execute("DELETE FROM social_profiles WHERE business_id = ?", (merge_id,))
            conn.execute("DELETE FROM data_evidence WHERE business_id = ?", (merge_id,))
            conn.execute("DELETE FROM businesses WHERE id = ?", (merge_id,))
            return True

    # ------------------------------------------------------------------
    # Freelance opportunities
    # ------------------------------------------------------------------
    @staticmethod
    def _freelance_key(platform: str, external_id: str, url: str) -> str:
        raw = f"{(platform or '').strip().lower()}|{(external_id or url or '').strip()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def upsert_freelance_opportunities(self, opportunities: list[dict[str, Any]]) -> tuple[int, int]:
        new_count = updated = 0
        with self.connect() as conn:
            for item in opportunities:
                dedup_key = item.get("dedup_key") or self._freelance_key(
                    item.get("platform", ""), item.get("external_id", ""), item.get("url", "")
                )
                existing = conn.execute(
                    "SELECT id, first_seen_at FROM freelance_opportunities WHERE dedup_key = ?",
                    (dedup_key,),
                ).fetchone()
                now = now_iso()
                if existing is None:
                    columns = [
                        "dedup_key", "platform", "external_id", "title", "description",
                        "url", "posted_at", "deadline", "budget_min", "budget_max",
                        "budget_type", "currency", "skills", "experience", "client_info",
                        "proposal_count", "project_status", "status_verified",
                        "last_checked_at", "first_seen_at", "last_seen_at", "is_new",
                        "match_score", "score_notes", "source_query", "is_demo",
                    ]
                    values = [
                        dedup_key, item.get("platform", ""), item.get("external_id", ""),
                        item.get("title", ""), item.get("description", ""), item.get("url", ""),
                        item.get("posted_at", ""), item.get("deadline", ""),
                        item.get("budget_min"), item.get("budget_max"),
                        item.get("budget_type", ""), item.get("currency", ""),
                        item.get("skills", ""), item.get("experience", ""),
                        item.get("client_info", ""), item.get("proposal_count"),
                        item.get("project_status", "Possibly open; status unconfirmed"),
                        int(bool(item.get("status_verified"))), now, now, now,
                        int(bool(item.get("is_new", 0))), int(item.get("match_score") or 0),
                        item.get("score_notes", ""), item.get("source_query", ""),
                        int(bool(item.get("is_demo"))),
                    ]
                    conn.execute(
                        f"INSERT INTO freelance_opportunities ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})",
                        values,
                    )
                    new_count += 1
                else:
                    fields = {
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "url": item.get("url", ""),
                        "posted_at": item.get("posted_at", ""),
                        "deadline": item.get("deadline", ""),
                        "budget_min": item.get("budget_min"),
                        "budget_max": item.get("budget_max"),
                        "budget_type": item.get("budget_type", ""),
                        "currency": item.get("currency", ""),
                        "skills": item.get("skills", ""),
                        "experience": item.get("experience", ""),
                        "client_info": item.get("client_info", ""),
                        "proposal_count": item.get("proposal_count"),
                        "project_status": item.get("project_status", ""),
                        "status_verified": int(bool(item.get("status_verified"))),
                        "last_checked_at": now,
                        "last_seen_at": now,
                        "match_score": int(item.get("match_score") or 0),
                        "score_notes": item.get("score_notes", ""),
                        "source_query": item.get("source_query", ""),
                    }
                    set_clause = ", ".join(f"{key} = ?" for key in fields)
                    conn.execute(
                        f"UPDATE freelance_opportunities SET {set_clause} WHERE id = ?",
                        list(fields.values()) + [existing["id"]],
                    )
                    updated += 1
        return new_count, updated

    def mark_new_freelance(self, previous_success_at: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE freelance_opportunities SET is_new = CASE WHEN first_seen_at > ? THEN 1 ELSE 0 END",
                (previous_success_at or "",),
            )
            return int(cur.rowcount or 0)

    def list_freelance(
        self,
        *,
        search: str = "",
        platforms: list[str] | None = None,
        statuses: list[str] | None = None,
        min_score: int | None = None,
        min_budget: float | None = None,
        max_budget: float | None = None,
        currency: str = "",
        new_only: bool = False,
        include_demo: bool = True,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where, params = [], []
        if search:
            like = f"%{search.strip()}%"
            where.append("(title LIKE ? OR description LIKE ? OR skills LIKE ? OR platform LIKE ?)")
            params.extend([like] * 4)
        if platforms:
            where.append(f"platform IN ({', '.join('?' for _ in platforms)})")
            params.extend(platforms)
        if statuses:
            where.append(f"project_status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if min_score is not None:
            where.append("match_score >= ?")
            params.append(int(min_score))
        if min_budget is not None:
            where.append("(budget_max IS NULL OR budget_max >= ?)")
            params.append(float(min_budget))
        if max_budget is not None:
            where.append("(budget_min IS NULL OR budget_min <= ?)")
            params.append(float(max_budget))
        if currency:
            where.append("(currency = '' OR currency = ?)")
            params.append(currency.upper())
        if new_only:
            where.append("is_new = 1")
        if not include_demo:
            where.append("is_demo = 0")
        sql = "SELECT * FROM freelance_opportunities"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY is_new DESC, match_score DESC, COALESCE(posted_at, '') DESC LIMIT ?"
        params.append(int(limit))
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def freelance_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN is_new = 1 THEN 1 ELSE 0 END) AS new,
                          SUM(CASE WHEN project_status = 'Open and verified' THEN 1 ELSE 0 END) AS verified_open,
                          SUM(CASE WHEN is_demo = 1 THEN 1 ELSE 0 END) AS demo
                   FROM freelance_opportunities"""
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN score >= 80 THEN 1 ELSE 0 END) AS high,
                          SUM(CASE WHEN score >= 60 AND score < 80 THEN 1 ELSE 0 END) AS medium,
                          SUM(CASE WHEN website_status = 'No website listed' THEN 1 ELSE 0 END) AS no_website,
                          SUM(CASE WHEN website_status IN ('Website unreachable','Website check failed') THEN 1 ELSE 0 END) AS broken,
                          SUM(CASE WHEN status IN ('contacted','Contacted') THEN 1 ELSE 0 END) AS contacted,
                          SUM(CASE WHEN status IN ('reviewed','Qualified') THEN 1 ELSE 0 END) AS reviewed,
                          SUM(CASE WHEN status = 'Won' THEN 1 ELSE 0 END) AS won
                   FROM businesses WHERE excluded = 0"""
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def clear_demo(self) -> int:
        with self.connect() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM businesses WHERE source = 'demo'").fetchall()]
            for business_id in ids:
                conn.execute("DELETE FROM social_profiles WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM crm_activities WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM outreach_drafts WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM data_evidence WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM website_audits WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
            conn.execute("DELETE FROM freelance_opportunities WHERE is_demo = 1")
            return len(ids)

    def backup(self, directory: str | Path | None = None) -> str:
        """Create a timestamped copy of the SQLite database and return its path."""
        source = Path(self.path)
        target_dir = Path(directory) if directory else source.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = target_dir / f"{source.stem}.backup_{stamp}{source.suffix}"
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        target.write_bytes(source.read_bytes())
        return str(target)
