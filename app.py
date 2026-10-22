"""MindSmiths Lead Intelligence - local Streamlit dashboard."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from config import (
    WEBSITE_STATUSES,
    ScoringRules,
    Settings,
    get_settings,
)
from mindsmiths.db import Database
from mindsmiths.discovery import DiscoveryError, SearchParams, validate_search
from mindsmiths.export import export_csv, export_excel
from mindsmiths.logging_utils import setup_logging
from mindsmiths.pipeline import SearchReport, re_enrich_all, rescore_all, run_search

st.set_page_config(
    page_title="MindSmiths Lead Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()
setup_logging(settings.log_path)


@st.cache_resource
def load_database(path: str) -> Database:
    return Database(path)


db = load_database(str(settings.db_path))

CATEGORIES = [
    "Photographers and photography studios",
    "Interior designers and architects",
    "Event planners and wedding services",
    "Coaching centres and training institutes",
    "Salons, spas and beauty businesses",
    "Restaurants, cafés and bakeries",
    "Clinics and local professional services",
    "Consultants and agencies",
    "Clothing, jewellery and product brands",
    "Other / custom category",
]

PROVIDERS = {
    "demo": "Demo data (fictional, no key needed)",
    "openstreetmap": "OpenStreetMap (free, no key needed)",
    "serpapi": "SerpAPI Google Maps (API key required)",
}


def social_for(record: dict, platform: str) -> dict | None:
    for social in record.get("socials") or []:
        if social.get("platform") == platform:
            return social
    return None


def followers_label(social: dict | None) -> str:
    if not social:
        return ""
    if social.get("followers") is not None and social.get("followers_verified"):
        return f"{int(social['followers']):,}"
    if social.get("followers") is not None:
        return f"~{int(social['followers']):,} (Needs manual verification)"
    return "Needs manual verification"


def execute_search(
    params: SearchParams, rules: ScoringRules
) -> tuple[SearchReport | None, str | None]:
    progress = st.progress(0.0)
    status = st.empty()

    def callback(stage: str, current: int, total: int, message: str) -> None:
        fraction = min(current / total, 1.0) if total else 0.08
        progress.progress(max(0.02, fraction))
        status.caption(message)

    try:
        report = run_search(db, settings, params, rules=rules, progress=callback)
        progress.progress(1.0)
        return report, None
    except (DiscoveryError, ValueError) as exc:
        progress.empty()
        status.empty()
        return None, str(exc)
    except Exception as exc:  # unexpected runtime errors must not kill the UI
        progress.empty()
        status.empty()
        return None, f"Search failed: {type(exc).__name__}. See logs/mindsmiths.log."


def show_report(report: SearchReport | None) -> None:
    if not report:
        return
    if report.errors:
        st.warning(f"{report.summary()}. Some items failed; see details below.")
        with st.expander("Collection report and limitations", expanded=True):
            for error in report.errors[:20]:
                st.write(f"- {error}")
            for note in report.limitations:
                st.write(f"- {note}")
    else:
        st.success(report.summary())
        with st.expander("Collection report and limitations"):
            st.write(f"Provider: **{report.provider}**")
            st.write(f"Query: `{report.query}`")
            for note in report.limitations:
                st.write(f"- {note}")


st.title("MindSmiths Lead Intelligence")
st.caption(
    "Business discovery and website-opportunity scoring for MindSmiths, "
    "backed by Melouz Technologies Pvt Ltd."
)

# Sidebar -------------------------------------------------------------------
with st.sidebar:
    st.header("Search")
    provider = st.selectbox(
        "Discovery source",
        options=list(PROVIDERS.keys()),
        format_func=lambda key: PROVIDERS[key],
        index=1,
    )
    if provider == "serpapi" and not settings.serpapi_key:
        st.warning("No SERPAPI_KEY configured. Add it to .env or use OpenStreetMap / Demo.")
    if provider == "openstreetmap":
        st.caption(
            "Free public OpenStreetMap data. No Google ratings, reviews or Maps place URLs. "
            "Coverage varies by locality."
        )
    settings.web_search_enabled = st.checkbox(
        "Deep web presence search",
        value=settings.web_search_enabled,
        help=(
            "Searches public index results for Instagram/Facebook/LinkedIn links, "
            "public phone numbers, emails and candidate websites. "
            "Uses DuckDuckGo for free, or SerpAPI Google when a key is configured."
        ),
    )

    with st.form("search_form"):
        city = st.text_input("City", value=settings.default_city)
        locality = st.text_input("Locality (optional)", placeholder="e.g. Anna Nagar")
        category_choice = st.selectbox("Business category", CATEGORIES, index=0)
        custom_category = st.text_input(
            "Custom category (used when 'Other' is selected)",
            placeholder="e.g. tattoo studios",
        )
        keywords = st.text_input(
            "Extra search keywords (optional)",
            placeholder="e.g. wedding portfolio",
        )
        max_results = st.slider("Maximum results", 5, 200, 40, step=5)
        c1, c2 = st.columns(2)
        with c1:
            min_followers = st.number_input("Min followers", 0, 10_000_000, 2000, step=500)
        with c2:
            active_days = st.number_input("Active within (days)", 1, 365, 30)
        submitted = st.form_submit_button("Find leads", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Scoring rules")
    with st.expander("Configure weights and thresholds"):
        no_website_pts = st.number_input("No website listed", 0, 100, 30)
        broken_pts = st.number_input("Website unreachable", 0, 100, 20)
        followers_pts = st.number_input("Verified followers threshold met", 0, 100, 15)
        activity_pts = st.number_input("Recent verified activity", 0, 100, 10)
        phone_pts = st.number_input("Phone available", 0, 100, 5)
        email_pts = st.number_input("Email available", 0, 100, 5)
        rating_pts = st.number_input("Strong rating + reviews", 0, 100, 10)
        match_pts = st.number_input("Strong social match", 0, 100, 5)
        strong_conf = st.slider("Strong match confidence", 0.5, 1.0, 0.8, 0.05)
    st.caption("Scores are prioritisation signals, not proof of purchase intent.")

    rules = ScoringRules(
        no_website=int(no_website_pts),
        broken_website=int(broken_pts),
        verified_followers=int(followers_pts),
        recent_activity=int(activity_pts),
        phone=int(phone_pts),
        email=int(email_pts),
        rating_reviews=int(rating_pts),
        strong_social_match=int(match_pts),
        min_followers=int(min_followers),
        active_days=int(active_days),
        strong_match_confidence=float(strong_conf),
    )

    if submitted:
        category = custom_category.strip() if category_choice == "Other / custom category" else category_choice
        params = SearchParams(
            city=city,
            locality=locality,
            category=category,
            keywords=keywords,
            max_results=int(max_results),
            provider=provider,
            min_followers=int(min_followers),
            active_days=int(active_days),
        )
        validation = validate_search(params)
        if validation:
            for error in validation:
                st.error(error)
        else:
            st.session_state["pending_search"] = (params, rules)
            st.rerun()

    st.divider()
    st.subheader("Local database")
    stats = db.stats()
    st.write(f"**{stats['total']}** stored leads · **{stats['high']}** high priority")
    if st.button("Load fictional demo leads", use_container_width=True):
        demo_params = SearchParams(
            city=settings.default_city,
            category=CATEGORIES[0],
            keywords="",
            max_results=200,
            provider="demo",
        )
        st.session_state["pending_search"] = (demo_params, rules)
        st.rerun()
    if st.button("Recalculate all scores", use_container_width=True):
        changed = rescore_all(db, rules)
        st.session_state["flash_message"] = f"Recalculated scores for {changed} leads."
        st.rerun()
    if st.button("Remove demo leads", use_container_width=True):
        removed = db.clear_demo()
        st.session_state["flash_message"] = f"Removed {removed} fictional demo leads."
        st.rerun()
    if st.button("Re-enrich stored leads", use_container_width=True):
        st.session_state["pending_reenrich"] = True
        st.rerun()

pending_reenrich = st.session_state.pop("pending_reenrich", None)
if pending_reenrich:
    progress = st.progress(0.0)
    status = st.empty()

    def refresh_callback(stage: str, current: int, total: int, message: str) -> None:
        progress.progress(min(current / total, 1.0) if total else 0.05)
        status.caption(message)

    refreshed = re_enrich_all(db, settings, rules, progress=refresh_callback)
    progress.progress(1.0)
    st.session_state["flash_message"] = (
        f"Re-enriched {refreshed} stored leads with contacts, socials and website checks."
    )
    st.rerun()

pending = st.session_state.pop("pending_search", None)
if pending:
    pending_params, pending_rules = pending
    report, error = execute_search(pending_params, pending_rules)
    if error:
        st.error(error)
    else:
        st.session_state["flash_report"] = report
        st.rerun()

flash_message = st.session_state.pop("flash_message", None)
if flash_message:
    st.info(flash_message)
show_report(st.session_state.pop("flash_report", None))

# Main results --------------------------------------------------------------
stats = db.stats()
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Stored leads", stats["total"])
m2.metric("High priority", stats["high"])
m3.metric("Medium priority", stats["medium"])
m4.metric("No website", stats["no_website"])
m5.metric("Broken/unreachable", stats["broken"])
m6.metric("Contacted", stats["contacted"])

st.subheader("Lead filters")
f1, f2, f3 = st.columns([1.2, 1.5, 1.3])
with f1:
    text_filter = st.text_input("Search stored leads", placeholder="Name, category, city, phone, email")
with f2:
    status_filter = st.multiselect("Website status filter", WEBSITE_STATUSES)
with f3:
    min_score = st.slider("Minimum lead score", 0, 100, 0, step=5)

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
with c1:
    no_website_only = st.checkbox("No website listed")
with c2:
    broken_only = st.checkbox("Website broken")
with c3:
    followers_only = st.checkbox(f"{int(min_followers):,}+ followers")
with c4:
    active_only = st.checkbox("Active social")
with c5:
    phone_only = st.checkbox("Phone available")
with c6:
    email_only = st.checkbox("Email available")
with c7:
    high_only = st.checkbox("High priority")

records = db.list_businesses(
    search=text_filter,
    website_statuses=status_filter or None,
    min_followers=int(min_followers) if followers_only else None,
    active_days=int(active_days) if active_only else None,
    phone_only=phone_only,
    email_only=email_only,
    high_priority_only=high_only,
    no_website_only=no_website_only,
    broken_only=broken_only,
    limit=1000,
)
if min_score:
    records = [record for record in records if int(record.get("score") or 0) >= min_score]

st.write(f"Showing **{len(records)}** lead(s). Missing values remain unknown and are not scored.")
if not records:
    st.info(
        "No leads match the current filters. Run a search, load the demo data, or relax the filters."
    )

if records:
    table_rows = []
    for record in records:
        instagram = social_for(record, "instagram")
        facebook = social_for(record, "facebook")
        linkedin = social_for(record, "linkedin")
        table_rows.append({
            "Business": record.get("name", ""),
            "Category": record.get("category", ""),
            "City": record.get("city", ""),
            "Locality": record.get("locality", ""),
            "Phone": record.get("phone", ""),
            "Email": record.get("email", ""),
            "Website status": record.get("website_status", "Unknown"),
            "Instagram": instagram.get("url", "") if instagram else "",
            "IG followers": followers_label(instagram),
            "Facebook": facebook.get("url", "") if facebook else "",
            "FB followers": followers_label(facebook),
            "LinkedIn": linkedin.get("url", "") if linkedin else "",
            "LI followers": followers_label(linkedin),
            "Rating": record.get("rating"),
            "Reviews": record.get("review_count"),
            "Score": record.get("score", 0),
            "Priority": record.get("priority", ""),
            "Qualification notes": record.get("qualification_notes", ""),
        })
    dataframe = pd.DataFrame(table_rows)
    st.dataframe(
        dataframe,
        hide_index=True,
        use_container_width=True,
        height=min(560, 42 + 35 * min(len(dataframe), 14)),
        column_config={
            "Instagram": st.column_config.LinkColumn("Instagram", display_text="Open"),
            "Facebook": st.column_config.LinkColumn("Facebook", display_text="Open"),
            "LinkedIn": st.column_config.LinkColumn("LinkedIn", display_text="Open"),
            "Rating": st.column_config.NumberColumn("Rating", format="%.1f"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        },
    )

    st.divider()
    st.subheader("Lead actions")
    options = {
        f"{record['name']} — score {record['score']} ({record['priority']})": record
        for record in records
    }
    selected_label = st.selectbox("Select a lead", list(options.keys()))
    record = options[selected_label]
    socials = {s["platform"]: s for s in record.get("socials") or []}

    detail_left, detail_right = st.columns([1.5, 1])
    with detail_left:
        st.markdown(f"**{record['name']}**")
        st.write(f"Category: {record.get('category') or 'Unknown'}")
        st.write(f"Address: {record.get('address') or 'Unknown'}")
        st.write(f"Phone: {record.get('phone') or 'Unknown'}")
        if record.get("phone_source"):
            st.write(f"Phone source: {record['phone_source']}")
        st.write(f"Email: {record.get('email') or 'Unknown'}")
        if record.get("email_source"):
            st.write(f"Email source: {record['email_source']}")
        st.write(f"Website: {record.get('website') or 'None listed'}")
        if record.get("website_source"):
            st.write(f"Website source: {record['website_source']}")
        st.write(f"Website status: **{record.get('website_status')}**")
        if record.get("website_http_status"):
            st.write(f"HTTP status: {record['website_http_status']}")
        if record.get("website_issues"):
            st.write(f"Website issues: {record['website_issues']}")
        st.write(f"Rating: {record.get('rating') if record.get('rating') is not None else 'Unknown'}")
        st.write(f"Reviews: {record.get('review_count') if record.get('review_count') is not None else 'Unknown'}")
        st.write(f"Source: {record.get('source')} · Collected: {record.get('collected_at')}")
        st.write(f"Sales status: **{record.get('status')}**")
        st.caption(
            "Follower counts are shown only when verified; otherwise they need manual verification "
            "and never add score."
        )

        link_cols = st.columns(4)
        if record.get("listing_url"):
            link_cols[0].link_button("Listing", record["listing_url"], use_container_width=True)
        if record.get("website"):
            link_cols[1].link_button("Website", record["website"], use_container_width=True)
        if record.get("contact_page"):
            link_cols[2].link_button("Contact page", record["contact_page"], use_container_width=True)
        if record.get("form_url"):
            link_cols[3].link_button("Enquiry form", record["form_url"], use_container_width=True)
        social_links = []
        for platform, icon in (("instagram", "Instagram"), ("facebook", "Facebook"), ("linkedin", "LinkedIn")):
            social = socials.get(platform)
            if social:
                label = f"{icon} ({followers_label(social)})"
                social_links.append((label, social["url"]))
        if social_links:
            cols = st.columns(len(social_links))
            for column, (label, url) in zip(cols, social_links):
                column.link_button(label, url, use_container_width=True)
        for platform in ("instagram", "facebook", "linkedin"):
            social = socials.get(platform)
            if social:
                st.caption(
                    f"{platform.title()} match confidence: "
                    f"{int(float(social.get('confidence') or 0) * 100)}% "
                    f"· source: {social.get('source') or 'unknown'}"
                )

    with detail_right:
        st.markdown("**Qualification notes**")
        st.write(record.get("qualification_notes") or "No scoring signals yet.")
        st.markdown("**Sales actions**")
        b1, b2 = st.columns(2)
        if b1.button("Mark reviewed", use_container_width=True):
            db.update_status(record["id"], "reviewed")
            st.rerun()
        if b2.button("Mark contacted", use_container_width=True):
            db.update_status(record["id"], "contacted")
            st.rerun()
        with st.form(f"notes_form_{record['id']}"):
            note_text = st.text_area("Notes", value=record.get("notes") or "", height=100)
            excluded = st.checkbox("Exclude duplicate / not a lead", value=record.get("excluded", False))
            saved = st.form_submit_button("Save notes and exclusion", use_container_width=True)
            if saved:
                db.update_notes(record["id"], note_text)
                db.set_excluded(record["id"], excluded)
                st.session_state["flash_message"] = "Lead updated."
                st.rerun()

    st.divider()
    st.subheader("Export")
    csv_data = export_csv(records)
    excel_data = export_excel(records)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    e1, e2 = st.columns(2)
    e1.download_button(
        "Download CSV",
        data=csv_data,
        file_name=f"mindsmiths_leads_{stamp}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    e2.download_button(
        "Download Excel",
        data=excel_data,
        file_name=f"mindsmiths_leads_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.caption(f"Exports reflect the {len(records)} currently filtered records. API keys are never exported.")

st.divider()
st.caption(
    "MindSmiths Lead Intelligence · MindSmiths, backed by Melouz Technologies Pvt Ltd · "
    "Local-first SQLite storage · Public data only · Follower counts marked "
    "'Needs manual verification' are unverified and unscored."
)

