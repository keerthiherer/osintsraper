"""SQLite persistence with conservative merge and deduplication."""
from __future__ import annotations

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
]

SOCIAL_COLUMNS = [
    "platform", "url", "followers", "followers_verified", "activity_verified",
    "last_active", "confidence", "source", "collected_at",
]

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
            for column in ("website_source", "phone_source", "email_source"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE businesses ADD COLUMN {column} TEXT DEFAULT ''")

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

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN score >= 80 THEN 1 ELSE 0 END) AS high,
                          SUM(CASE WHEN score >= 60 AND score < 80 THEN 1 ELSE 0 END) AS medium,
                          SUM(CASE WHEN website_status = 'No website listed' THEN 1 ELSE 0 END) AS no_website,
                          SUM(CASE WHEN website_status IN ('Website unreachable','Website check failed') THEN 1 ELSE 0 END) AS broken,
                          SUM(CASE WHEN status = 'contacted' THEN 1 ELSE 0 END) AS contacted,
                          SUM(CASE WHEN status = 'reviewed' THEN 1 ELSE 0 END) AS reviewed
                   FROM businesses WHERE excluded = 0"""
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def clear_demo(self) -> int:
        with self.connect() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM businesses WHERE source = 'demo'").fetchall()]
            for business_id in ids:
                conn.execute("DELETE FROM social_profiles WHERE business_id = ?", (business_id,))
                conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
            return len(ids)
