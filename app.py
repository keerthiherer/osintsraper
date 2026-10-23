"""MindSmiths Sales Intelligence Platform - local Streamlit dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from config import (
    BUDGET_FITS,
    CRM_STATUSES,
    FREELANCE_STATUSES,
    OPPORTUNITY_CLASSES,
    REVENUE_CATEGORIES,
    WEBSITE_STATUSES,
    OpportunityRules,
    ScoringRules,
    get_settings,
    save_dataclass,
)
from mindsmiths.audit import audit_website
from mindsmiths.db import Database
from mindsmiths.discovery import DiscoveryError, SearchParams, validate_search
from mindsmiths.export import (
    export_csv,
    export_excel,
    export_freelance_csv,
    export_freelance_excel,
)
from mindsmiths.freelance import (
    FreelanceSearch,
    all_providers,
    provider_statuses,
    search_opportunities,
)
from mindsmiths.logging_utils import setup_logging
from mindsmiths.models import now_iso
from mindsmiths.opportunity import OpportunityResult, score_opportunity
from mindsmiths.outreach import CHANNELS, OFFERS, TONES, generate_outreach
from mindsmiths.pipeline import (
    SearchReport,
    re_enrich_all,
    record_business_evidence,
    refresh_intelligence,
    rescore_all,
    run_search,
)
from mindsmiths.pricing import PricingCatalogue, load_catalogue, save_catalogue
from mindsmiths.quotation import (
    FEATURES,
    WEBSITE_TYPES,
    QuoteScope,
    build_quote_html,
    build_quote_pdf,
    default_scope,
    quote_summary,
    recommend_quote,
)
from mindsmiths.revenue import RevenueAssessment, assess_revenue

st.set_page_config(
    page_title="MindSmiths Sales Intelligence",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def social_for(record: dict[str, Any], platform: str) -> dict[str, Any] | None:
    for social in record.get("socials") or []:
        if social.get("platform") == platform:
            return social
    return None


def followers_label(social: dict[str, Any] | None) -> str:
    if not social:
        return ""
    if social.get("followers") is not None and social.get("followers_verified"):
        return f"{int(social['followers']):,}"
    if social.get("followers") is not None:
        return f"~{int(social['followers']):,} (Needs manual verification)"
    return "Needs manual verification"


def fmt_inr(value: Any) -> str:
    try:
        return f"₹{float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def parse_number(value: str) -> float | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_json(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
        return payload if isinstance(payload, dict) else {}
    except (ValueError, TypeError):
        return {}


def lead_records(limit: int = 2000) -> list[dict[str, Any]]:
    return db.list_businesses(limit=limit, include_excluded=False)


def lead_options(records: list[dict[str, Any]]) -> tuple[list[int], dict[int, dict[str, Any]]]:
    mapping = {int(record["id"]): record for record in records}
    options = list(mapping.keys())
    return options, mapping


def lead_label(record: dict[str, Any]) -> str:
    score = record.get("opportunity_score") or 0
    classification = record.get("opportunity_class") or "Needs more research"
    return f"{record.get('name', 'Unnamed')} · opportunity {score} · {classification}"


def analysis_for(
    record: dict[str, Any],
    opportunity_rules: OpportunityRules,
) -> tuple[RevenueAssessment, OpportunityResult]:
    evidence = db.evidence_for(int(record["id"]))
    revenue = assess_revenue(record, rules=opportunity_rules, evidence_records=evidence)
    opportunity = score_opportunity(record, rules=opportunity_rules, revenue=revenue)
    return revenue, opportunity


def save_analysis(record: dict[str, Any], opportunity_rules: OpportunityRules) -> tuple[RevenueAssessment, OpportunityResult]:
    revenue, opportunity = analysis_for(record, opportunity_rules)
    db.update_revenue(
        int(record["id"]),
        category=revenue.category,
        band=revenue.band,
        confidence=revenue.confidence,
        assessment_json=json.dumps(revenue.to_dict(), ensure_ascii=False, default=str),
    )
    db.update_opportunity(
        int(record["id"]),
        score=opportunity.score,
        classification=opportunity.classification,
        budget_fit=opportunity.budget_fit,
        confidence=opportunity.confidence,
        notes=opportunity.why,
    )
    return revenue, opportunity


def execute_search(params: SearchParams, rules: ScoringRules) -> tuple[SearchReport | None, str | None]:
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


def save_lead_analysis_button(record: dict[str, Any], rules: OpportunityRules, key: str) -> None:
    if st.button("Recompute this lead's intelligence", key=key, width="stretch"):
        revenue, opportunity = save_analysis(record, rules)
        st.session_state["flash_message"] = (
            f"Saved intelligence for {record.get('name')}: opportunity {opportunity.score} "
            f"({opportunity.classification}), budget fit {revenue.affordability}."
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Sidebar: discovery search and scoring rules
# ---------------------------------------------------------------------------
opportunity_rules = settings.load_opportunity_rules()
pricing_catalogue = load_catalogue(settings.pricing_catalogue_path)
min_followers = 2000
active_days = 30

with st.sidebar:
    st.header("Business discovery")
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
        submitted = st.form_submit_button("Find leads", type="primary", width="stretch")

    st.divider()
    st.subheader("Lead scoring rules")
    with st.expander("Configure legacy lead-score weights"):
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
    if st.button("Load fictional demo leads", width="stretch"):
        demo_params = SearchParams(
            city=settings.default_city,
            category=CATEGORIES[0],
            keywords="",
            max_results=200,
            provider="demo",
        )
        st.session_state["pending_search"] = (demo_params, rules)
        st.rerun()
    if st.button("Recalculate all scores", width="stretch"):
        changed = rescore_all(db, rules, opportunity_rules=opportunity_rules)
        st.session_state["flash_message"] = f"Recalculated scores and intelligence for {changed} leads."
        st.rerun()
    if st.button("Re-enrich stored leads", width="stretch"):
        st.session_state["pending_reenrich"] = True
        st.rerun()
    if st.button("Remove demo leads", width="stretch"):
        removed = db.clear_demo()
        st.session_state["flash_message"] = f"Removed {removed} fictional demo leads."
        st.rerun()
    if st.button("Back up database now", width="stretch"):
        path = db.backup(settings.data_dir)
        st.session_state["flash_message"] = f"Database backup created: {path}"
        st.rerun()

# Process queued work before rendering tabs
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

st.title("MindSmiths Sales Intelligence")
st.caption(
    "Business discovery, revenue intelligence, website opportunity scoring, quotations, "
    "freelance opportunities and CRM for MindSmiths, backed by Melouz Technologies Pvt Ltd."
)
st.caption(
    "All scores are transparent prioritisation signals from public evidence. They are not "
    "predictions of purchase intent and never invented revenue."
)

tabs = st.tabs([
    "Business Discovery",
    "Lead Intelligence",
    "Website Audit",
    "Quotation Assistant",
    "Freelance Opportunities",
    "Sales CRM",
    "Settings and Data Sources",
])


# ---------------------------------------------------------------------------
# Tab 1: Business discovery
# ---------------------------------------------------------------------------
with tabs[0]:
    stats = db.stats()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Stored leads", stats["total"])
    m2.metric("High lead score", stats["high"])
    m3.metric("Medium lead score", stats["medium"])
    m4.metric("No website listed", stats["no_website"])
    m5.metric("Broken/unreachable", stats["broken"])
    m6.metric("Contacted", stats["contacted"])

    st.subheader("Lead filters")
    f1, f2, f3 = st.columns([1.2, 1.5, 1.3])
    with f1:
        text_filter = st.text_input("Search stored leads", placeholder="Name, category, city, phone, email", key="disc_search")
    with f2:
        status_filter = st.multiselect("Website status filter", WEBSITE_STATUSES, key="disc_web_status")
    with f3:
        min_score = st.slider("Minimum lead score", 0, 100, 0, step=5, key="disc_min_score")

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        no_website_only = st.checkbox("No website listed", key="disc_no_site")
    with c2:
        broken_only = st.checkbox("Website broken", key="disc_broken")
    with c3:
        followers_only = st.checkbox(f"{int(min_followers):,}+ followers", key="disc_followers")
    with c4:
        active_only = st.checkbox("Active social", key="disc_active")
    with c5:
        phone_only = st.checkbox("Phone available", key="disc_phone")
    with c6:
        email_only = st.checkbox("Email available", key="disc_email")
    with c7:
        high_only = st.checkbox("High lead score", key="disc_high")

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
        st.info("No leads match the current filters. Run a search, load the demo data, or relax the filters.")

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
                "Lead score": record.get("score", 0),
                "Opportunity": record.get("opportunity_score", 0),
                "Opportunity class": record.get("opportunity_class", ""),
                "Budget fit": record.get("budget_fit", ""),
                "Priority": record.get("priority", ""),
            })
        dataframe = pd.DataFrame(table_rows)
        st.dataframe(
            dataframe,
            hide_index=True,
            width="stretch",
            height=min(560, 42 + 35 * min(len(dataframe), 14)),
            column_config={
                "Instagram": st.column_config.LinkColumn("Instagram", display_text="Open"),
                "Facebook": st.column_config.LinkColumn("Facebook", display_text="Open"),
                "LinkedIn": st.column_config.LinkColumn("LinkedIn", display_text="Open"),
                "Rating": st.column_config.NumberColumn("Rating", format="%.1f"),
                "Lead score": st.column_config.ProgressColumn("Lead score", min_value=0, max_value=100, format="%d"),
                "Opportunity": st.column_config.ProgressColumn("Opportunity", min_value=0, max_value=100, format="%d"),
            },
        )

        st.divider()
        st.subheader("Lead actions")
        options, mapping = lead_options(records)
        selected_id = st.selectbox(
            "Select a lead", options, format_func=lambda value: lead_label(mapping[value]),
            key="disc_selected_lead",
        )
        record = db.get_business(selected_id) or mapping[selected_id]
        socials = {item["platform"]: item for item in record.get("socials") or []}

        detail_left, detail_right = st.columns([1.5, 1])
        with detail_left:
            st.markdown(f"**{record['name']}**")
            st.write(f"Category: {record.get('category') or 'Unknown'}")
            st.write(f"Address: {record.get('address') or 'Unknown'}")
            st.write(f"Phone: {record.get('phone') or 'Unknown'}")
            st.write(f"Email: {record.get('email') or 'Unknown'}")
            st.write(f"Website: {record.get('website') or 'None listed'}")
            st.write(f"Website status: **{record.get('website_status')}**")
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
                link_cols[0].link_button("Listing", record["listing_url"], width="stretch")
            if record.get("website"):
                link_cols[1].link_button("Website", record["website"], width="stretch")
            if record.get("contact_page"):
                link_cols[2].link_button("Contact page", record["contact_page"], width="stretch")
            if record.get("form_url"):
                link_cols[3].link_button("Enquiry form", record["form_url"], width="stretch")
            social_links = []
            for platform, icon in (("instagram", "Instagram"), ("facebook", "Facebook"), ("linkedin", "LinkedIn")):
                social = socials.get(platform)
                if social:
                    social_links.append((f"{icon} ({followers_label(social)})", social["url"]))
            if social_links:
                cols = st.columns(len(social_links))
                for column, (label, url) in zip(cols, social_links):
                    column.link_button(label, url, width="stretch")

        with detail_right:
            st.markdown("**Qualification notes**")
            st.write(record.get("qualification_notes") or "No scoring signals yet.")
            st.markdown("**Sales actions**")
            b1, b2 = st.columns(2)
            if b1.button("Mark qualified", width="stretch", key="disc_qualified"):
                db.update_crm(record["id"], {"status": "Qualified"})
                st.rerun()
            if b2.button("Mark contacted", width="stretch", key="disc_contacted"):
                db.update_crm(record["id"], {"status": "Contacted", "last_contact_date": date.today().isoformat()})
                db.add_activity(record["id"], "Marked contacted from discovery.")
                st.rerun()
            save_lead_analysis_button(record, opportunity_rules, "disc_recompute")
            with st.form(f"notes_form_{record['id']}"):
                note_text = st.text_area("Notes", value=record.get("notes") or "", height=100)
                excluded = st.checkbox("Exclude duplicate / not a lead", value=record.get("excluded", False))
                saved = st.form_submit_button("Save notes and exclusion", width="stretch")
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
            "Download CSV", data=csv_data, file_name=f"mindsmiths_leads_{stamp}.csv",
            mime="text/csv", width="stretch",
        )
        e2.download_button(
            "Download Excel", data=excel_data, file_name=f"mindsmiths_leads_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        st.caption(f"Exports reflect the {len(records)} currently filtered records. API keys are never exported.")


# ---------------------------------------------------------------------------
# Tab 2: Lead intelligence
# ---------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Revenue intelligence and website purchase opportunity")
    st.caption(
        "Revenue is only presented as fact when a public disclosure is recorded. Otherwise the "
        "system shows a broad business-size/affordability band with its evidence. Review counts "
        "are never multiplied by an invented purchase value."
    )
    records = lead_records()
    if not records:
        st.info("No leads yet. Run a business discovery search or load the demo data first.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            intel_search = st.text_input("Search leads", key="intel_search", placeholder="Name, city, category")
        with f2:
            intel_classes = st.multiselect("Opportunity class", OPPORTUNITY_CLASSES, key="intel_class")
        with f3:
            intel_budget = st.multiselect("Budget fit", BUDGET_FITS, key="intel_budget")
        with f4:
            intel_min = st.slider("Minimum opportunity score", 0, 100, 0, step=5, key="intel_min")
        filtered = [
            record for record in records
            if (not intel_search or intel_search.lower() in f"{record.get('name','')} {record.get('city','')} {record.get('category','')}".lower())
            and (not intel_classes or record.get("opportunity_class") in intel_classes)
            and (not intel_budget or record.get("budget_fit") in intel_budget)
            and int(record.get("opportunity_score") or 0) >= intel_min
        ]
        st.write(f"Showing **{len(filtered)}** lead(s).")
        if filtered:
            options, mapping = lead_options(filtered)
            selected_id = st.selectbox(
                "Select a lead to inspect", options,
                format_func=lambda value: lead_label(mapping[value]), key="intel_selected",
            )
            record = db.get_business(selected_id) or mapping[selected_id]
            revenue, opportunity = analysis_for(record, opportunity_rules)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Website opportunity", f"{opportunity.score}/100")
            m2.metric("Classification", opportunity.classification)
            m3.metric("Evidence confidence", opportunity.confidence.title())
            m4.metric("Budget fit", revenue.affordability.title())
            m5.metric("Business size band", revenue.band)
            st.caption(f"Last saved: {record.get('opportunity_updated_at') or 'not yet saved'}")

            left, right = st.columns([1.2, 1])
            with left:
                st.markdown("### Why this prospect may need a website")
                st.write(opportunity.why)
                st.markdown("### Signal breakdown")
                signal_rows = [
                    {"Signal": signal.name, "State": signal.state, "Points": signal.points, "Evidence": signal.evidence}
                    for signal in opportunity.signals
                ]
                st.dataframe(pd.DataFrame(signal_rows), hide_index=True, width="stretch")
                if opportunity.unknown:
                    st.info("Unknown / not verified: " + ", ".join(opportunity.unknown))
            with right:
                st.markdown("### Recommended offer")
                st.write(opportunity.recommended_offer)
                st.markdown("### Recommended next action")
                st.write(opportunity.next_action)
                st.markdown("### Potential objections")
                for item in opportunity.objections:
                    st.write(f"- {item}")
                save_lead_analysis_button(record, opportunity_rules, "intel_recompute")

            st.divider()
            st.markdown("### Revenue assessment")
            r1, r2, r3 = st.columns(3)
            r1.metric("Evidence category", revenue.category)
            r2.metric("Confidence", revenue.confidence.title())
            r3.metric("Estimated on", revenue.estimated_at)
            if revenue.revenue_range:
                st.write(f"**Estimated range:** {fmt_inr(revenue.revenue_range[0])} – {fmt_inr(revenue.revenue_range[1])}")
            else:
                st.write("**Estimated revenue range:** Not defensible from the available evidence. No rupee revenue figure is claimed.")
            st.write(f"**Method:** {revenue.method}")
            if revenue.warning:
                st.warning(revenue.warning)
            if revenue.evidence:
                st.write("**Evidence used**")
                for item in revenue.evidence:
                    st.write(f"- {item}")
            if revenue.sources:
                st.write("**Sources**")
                for url in revenue.sources:
                    st.write(f"- {url}")

            st.divider()
            st.markdown("### Manual public evidence")
            st.caption(
                "Only enter facts you can support with a source. Leave fields blank when unknown. "
                "Do not enter sensitive personal data."
            )
            with st.form(f"intel_evidence_form_{record['id']}"):
                e1, e2, e3 = st.columns(3)
                with e1:
                    locations = st.text_input("Number of public locations", value="" if record.get("number_of_locations") is None else str(record["number_of_locations"]))
                with e2:
                    catalogue = st.text_input("Public catalogue size", value="" if record.get("catalogue_size") is None else str(record["catalogue_size"]))
                with e3:
                    services = st.text_input("Public services summary", value=record.get("services_summary") or "")
                e4, e5, e6 = st.columns(3)
                with e4:
                    price_min = st.text_input("Public price min (INR)", value="" if record.get("product_price_min") is None else str(record["product_price_min"]))
                with e5:
                    price_max = st.text_input("Public price max (INR)", value="" if record.get("product_price_max") is None else str(record["product_price_max"]))
                with e6:
                    st.caption("Unknown is a valid state.")
                tri_options = ["Unknown", "Yes", "No"]
                t1, t2, t3, t4, t5 = st.columns(5)
                with t1:
                    booking_choice = st.selectbox(
                        "Booking facility",
                        tri_options,
                        index=0 if record.get("has_booking") is None else (1 if record.get("has_booking") else 2),
                    )
                with t2:
                    enquiry_choice = st.selectbox(
                        "Enquiry facility",
                        tri_options,
                        index=0 if record.get("has_enquiry") is None else (1 if record.get("has_enquiry") else 2),
                    )
                with t3:
                    promotes_choice = st.selectbox(
                        "Promotes services",
                        tri_options,
                        index=0 if record.get("promotes_services") is None else (1 if record.get("promotes_services") else 2),
                    )
                with t4:
                    expansion_choice = st.selectbox(
                        "Public expansion/new branch",
                        tri_options,
                        index=0 if record.get("expansion_signal") is None else (1 if record.get("expansion_signal") else 2),
                    )
                with t5:
                    established_choice = st.selectbox(
                        "Established operations evidence",
                        tri_options,
                        index=0 if record.get("established_signal") is None else (1 if record.get("established_signal") else 2),
                    )
                v1, v2 = st.columns(2)
                with v1:
                    verified_revenue = st.text_input(
                        "Verified public revenue (INR, only with a disclosure)",
                        value="" if record.get("verified_revenue") is None else str(record["verified_revenue"]),
                    )
                    verified_source = st.text_input(
                        "Verified revenue source URL/note",
                        value=record.get("verified_revenue_source") or "",
                    )
                with v2:
                    third_party = st.text_input(
                        "Third-party revenue estimate (INR, cited)",
                        value="" if record.get("third_party_revenue") is None else str(record["third_party_revenue"]),
                    )
                    third_party_source = st.text_input(
                        "Third-party estimate source URL/note",
                        value=record.get("third_party_revenue_source") or "",
                    )
                saved_evidence = st.form_submit_button("Save evidence and recompute", width="stretch")
                if saved_evidence:
                    def tri(value: str) -> bool | None:
                        return None if value == "Unknown" else value == "Yes"

                    fields = {
                        "number_of_locations": int(parse_number(locations)) if parse_number(locations) is not None else None,
                        "catalogue_size": int(parse_number(catalogue)) if parse_number(catalogue) is not None else None,
                        "services_summary": services.strip(),
                        "product_price_min": parse_number(price_min),
                        "product_price_max": parse_number(price_max),
                        "has_booking": tri(booking_choice),
                        "has_enquiry": tri(enquiry_choice),
                        "promotes_services": tri(promotes_choice),
                        "expansion_signal": tri(expansion_choice),
                        "established_signal": tri(established_choice),
                        "verified_revenue": parse_number(verified_revenue),
                        "verified_revenue_source": verified_source.strip(),
                        "third_party_revenue": parse_number(third_party),
                        "third_party_revenue_source": third_party_source.strip(),
                    }
                    db.update_business_fields(record["id"], fields)
                    updated = db.get_business(record["id"])
                    if updated:
                        if fields["verified_revenue"]:
                            has_source = bool(fields["verified_revenue_source"])
                            db.record_evidence(
                                record["id"], "verified_revenue", fields["verified_revenue"],
                                source_url=fields["verified_revenue_source"],
                                state="verified" if has_source else "unverified",
                                confidence="high" if has_source else "low",
                                reason=(
                                    "Public revenue disclosure entered manually."
                                    if has_source
                                    else "Revenue figure entered without a source; not treated as verified."
                                ),
                            )
                        if fields["third_party_revenue"]:
                            has_source = bool(fields["third_party_revenue_source"])
                            db.record_evidence(
                                record["id"], "third_party_revenue", fields["third_party_revenue"],
                                source_url=fields["third_party_revenue_source"],
                                state="unverified",
                                confidence="medium" if has_source else "low",
                                reason=(
                                    "Third-party estimate entered manually."
                                    if has_source
                                    else "Third-party estimate entered without a citation."
                                ),
                            )
                        record_business_evidence(db, record["id"], updated)
                        save_analysis(updated, opportunity_rules)
                    st.session_state["flash_message"] = "Evidence saved and intelligence recomputed."
                    st.rerun()

            evidence_rows = db.evidence_for(record["id"])
            if evidence_rows:
                st.markdown("### Stored evidence trail")
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Field": item["field_name"], "Value": item["value"],
                            "Source URL": item["source_url"], "State": item["state"],
                            "Confidence": item["confidence"], "Reason": item["reason"],
                            "Collected": item["collected_at"], "Last checked": item["last_checked_at"],
                        }
                        for item in evidence_rows
                    ]),
                    hide_index=True, width="stretch", height=240,
                )
        else:
            st.info("No leads match these filters.")

        if st.button("Recompute and save intelligence for all leads", width="stretch"):
            for record in records:
                save_analysis(record, opportunity_rules)
            st.session_state["flash_message"] = f"Recomputed intelligence for {len(records)} leads."
            st.rerun()


# ---------------------------------------------------------------------------
# Tab 3: Website audit
# ---------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Website audit and upsell opportunities")
    st.caption(
        "Lightweight homepage and contact-page checks only. No vulnerability scanning or full-site crawl. "
        "A missing metadata field alone is not a reason to call a site bad."
    )
    records = lead_records()
    if not records:
        st.info("No leads yet. Run a business discovery search or load the demo data first.")
    else:
        options, mapping = lead_options(records)
        selected_id = st.selectbox(
            "Select a lead to audit", options,
            format_func=lambda value: f"{mapping[value].get('name')} · {mapping[value].get('website_status')}",
            key="audit_selected",
        )
        record = db.get_business(selected_id) or mapping[selected_id]
        a1, a2, a3 = st.columns(3)
        a1.metric("Website status", record.get("website_status") or "Unknown")
        a2.metric("Last audit", record.get("audit_checked_at") or "Never")
        a3.metric("Response time", f"{record.get('website_response_ms')} ms" if record.get("website_response_ms") else "Unknown")
        if record.get("website"):
            st.write(f"Website: {record['website']}")
        if record.get("website_issues"):
            st.write(f"Stored issues: {record['website_issues']}")

        if st.button("Run website audit now", type="primary", key="audit_run"):
            with st.spinner("Checking the homepage and contact page..."):
                audit = audit_website(record.get("website"), settings=settings, contact_page=record.get("contact_page") or "")
            db.update_audit(record["id"], status=audit.status, report_json=audit.to_json(), error=audit.error)
            db.update_business_fields(record["id"], {
                "website_status": audit.status,
                "website_response_ms": audit.response_time_ms,
                "website_page_bytes": audit.page_size_bytes,
                "has_booking": audit.has_booking,
                "has_enquiry": audit.has_enquiry,
                "has_cta": audit.has_cta,
            })
            record_business_evidence(db, record["id"], db.get_business(record["id"]) or record)
            updated = db.get_business(record["id"])
            if updated:
                save_analysis(updated, opportunity_rules)
            st.session_state["flash_message"] = "Website audit completed and intelligence refreshed."
            st.rerun()

        stored = parse_json(record.get("audit_report") or "")
        if stored:
            st.markdown(f"### {stored.get('summary', 'Audit report')}")
            checks = stored.get("checks") or []
            if checks:
                st.dataframe(
                    pd.DataFrame([
                        {"Check": item.get("name"), "State": item.get("state"), "Detail": item.get("detail"), "Evidence": item.get("evidence")}
                        for item in checks
                    ]),
                    hide_index=True, width="stretch",
                )
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Findings**")
                for item in stored.get("findings") or []:
                    st.write(f"- {item}")
                st.markdown("**What could not be checked**")
                for item in stored.get("limitations") or []:
                    st.write(f"- {item}")
            with c2:
                st.markdown("**Recommendations**")
                for item in stored.get("recommendations") or []:
                    st.write(f"- {item}")
                st.markdown("**MindSmiths services that may help**")
                for item in stored.get("services") or []:
                    st.write(f"- {item}")
        else:
            st.info("No audit has been stored for this lead yet.")


# ---------------------------------------------------------------------------
# Tab 4: Quotation assistant
# ---------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Smart quotation assistant")
    st.caption(
        "Quotes are based on the configured scope and pricing catalogue. Business size can inform the "
        "package suggestion but never automatically inflates the price."
    )
    records = lead_records()
    if not records:
        st.info("No leads yet. Run a business discovery search or load the demo data first.")
    else:
        options, mapping = lead_options(records)
        selected_id = st.selectbox(
            "Select a client business", options,
            format_func=lambda value: lead_label(mapping[value]), key="quote_selected",
        )
        record = db.get_business(selected_id) or mapping[selected_id]
        revenue, opportunity = analysis_for(record, opportunity_rules)
        st.write(
            f"Budget fit: **{revenue.affordability}** · Business size band: **{revenue.band}** · "
            f"Website opportunity: **{opportunity.score}/100**"
        )
        if revenue.affordability == "unknown":
            st.info("Budget information is unavailable. This is a standard scope-based quotation; ask about requirements before finalising.")

        defaults = default_scope(record, revenue)
        with st.form(f"quote_form_{record['id']}"):
            q1, q2, q3 = st.columns(3)
            with q1:
                website_type = st.selectbox(
                    "Website type", list(WEBSITE_TYPES.keys()),
                    index=list(WEBSITE_TYPES.keys()).index(defaults.website_type),
                    format_func=lambda key: WEBSITE_TYPES[key],
                )
            with q2:
                pages = st.number_input("Number of pages", 1, 100, int(defaults.pages))
            with q3:
                maintenance_months = st.number_input("Maintenance duration (months)", 0, 36, int(defaults.maintenance_months))
            feature_keys = list(FEATURES.keys())
            default_features = [feature for feature in defaults.features if feature in feature_keys]
            features = st.multiselect(
                "Features",
                feature_keys,
                default=default_features,
                format_func=lambda key: FEATURES[key],
            )
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                content_pages = st.number_input("Content pages to write", 0, 50, 0)
            with f2:
                integrations = st.number_input("Custom integrations", 0, 10, 0)
            with f3:
                support_hours = st.number_input("Additional support hours", 0, 100, 0)
            with f4:
                timeline_days = st.number_input("Delivery timeline override (days, 0 = auto)", 0, 365, 0)
            include_hosting = st.checkbox("Include hosting and domain (annual)", value=False)
            st.caption(
                f"Catalogue limits: {fmt_inr(pricing_catalogue.minimum_project_price)} – "
                f"{fmt_inr(pricing_catalogue.maximum_project_price)}. Edit the catalogue in Settings."
            )
            submitted = st.form_submit_button("Recommend quotation", type="primary", width="stretch")

        scope = QuoteScope(
            website_type=website_type,
            pages=int(pages),
            features=features,
            content_pages=int(content_pages),
            integrations=int(integrations),
            maintenance_months=int(maintenance_months),
            include_hosting_domain=include_hosting,
            additional_support_hours=int(support_hours),
            timeline_days=int(timeline_days) or None,
        )
        quote = recommend_quote(record, revenue, scope, pricing_catalogue)
        st.session_state[f"quote_{record['id']}"] = (scope, quote)
        st.markdown("### Recommendation")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Recommended package", quote.package_name)
        q2.metric("Suggested range", f"{fmt_inr(quote.min_price)} – {fmt_inr(quote.max_price)}")
        q3.metric("Estimated delivery", f"{quote.delivery_days} days")
        q4.metric("Implementation effort", quote.effort)
        st.caption(quote_summary(quote))
        st.markdown("**Price breakdown**")
        st.dataframe(pd.DataFrame(quote.line_items), hide_index=True, width="stretch")
        if quote.maintenance_total:
            st.write(f"Maintenance: **{fmt_inr(quote.maintenance_monthly)}/month** for {maintenance_months} month(s) = **{fmt_inr(quote.maintenance_total)}**.")
        else:
            st.write("Maintenance: not included in this quotation.")
        st.write("**Reasons for the recommendation**")
        for reason in quote.reasons:
            st.write(f"- {reason}")
        st.write("**Optional add-ons**")
        for addon in quote.addons:
            st.write(f"- {addon}")
        with st.expander("Assumptions and exclusions"):
            st.write("**Assumptions**")
            for item in quote.assumptions:
                st.write(f"- {item}")
            st.write("**Exclusions**")
            for item in quote.exclusions:
                st.write(f"- {item}")

        prepared_on = date.today()
        pdf_bytes = None
        pdf_error = ""
        try:
            pdf_bytes = build_quote_pdf(
                record.get("name") or "Client",
                scope,
                quote,
                pricing_catalogue,
                company_name=settings.company_name,
                company_parent=settings.company_parent,
                company_contact=settings.company_contact,
                company_website=settings.company_website,
                prepared_on=prepared_on,
            )
        except Exception as exc:  # reportlab missing or font/build issue
            pdf_error = f"PDF generation failed: {type(exc).__name__}. Use the print-ready HTML version."
        html = build_quote_html(
            record.get("name") or "Client",
            scope,
            quote,
            pricing_catalogue,
            company_name=settings.company_name,
            company_parent=settings.company_parent,
            company_contact=settings.company_contact,
            company_website=settings.company_website,
            prepared_on=prepared_on,
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        d1, d2 = st.columns(2)
        if pdf_bytes:
            d1.download_button(
                "Download quotation PDF",
                data=pdf_bytes,
                file_name=f"mindsmiths_quote_{stamp}.pdf",
                mime="application/pdf",
                width="stretch",
            )
        else:
            d1.warning(pdf_error)
        d2.download_button(
            "Download print-ready HTML",
            data=html.encode("utf-8"),
            file_name=f"mindsmiths_quote_{stamp}.html",
            mime="text/html",
            width="stretch",
        )
        c1, c2 = st.columns(2)
        midpoint = int((quote.min_price + quote.max_price) / 2)
        if c1.button("Save as proposed quotation", width="stretch", key="quote_save_proposed"):
            db.update_crm(record["id"], {"proposed_quotation": midpoint})
            db.add_activity(record["id"], f"Quotation recommendation saved: {quote.package_name} ({fmt_inr(quote.min_price)}–{fmt_inr(quote.max_price)}).", "quotation")
            st.session_state["flash_message"] = "Proposed quotation saved to CRM."
            st.rerun()
        if c2.button("Mark quotation sent", width="stretch", key="quote_mark_sent"):
            db.update_crm(record["id"], {
                "quoted_amount": midpoint,
                "status": "Quotation sent",
                "last_contact_date": date.today().isoformat(),
            })
            db.add_activity(record["id"], f"Quotation sent: {quote.package_name} at {fmt_inr(midpoint)}.", "quotation")
            st.session_state["flash_message"] = "Quotation amount recorded and lead marked Quotation sent."
            st.rerun()


# ---------------------------------------------------------------------------
# Tab 5: Freelance opportunities
# ---------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Freelance web development opportunities")
    st.caption(
        "Live listings from public APIs only. Never submit bids automatically. "
        "Upwork requires an OAuth token; PeoplePerHour and Guru have no documented public API and are manual-only."
    )
    statuses = provider_statuses(settings)
    with st.expander("Provider configuration and limitations", expanded=False):
        st.dataframe(
            pd.DataFrame([
                {
                    "Provider": status.label, "State": status.state,
                    "Requires key": "Yes" if status.requires_key else "No",
                    "Detail": status.detail, "Docs": status.docs_url,
                }
                for status in statuses
            ]),
            hide_index=True, width="stretch",
        )
    live_platforms = [
        status.name for status in statuses
        if status.name not in {"demo"} and status.state in {"available", "configured"}
    ]
    with st.form("freelance_search_form"):
        s1, s2 = st.columns([2, 1])
        with s1:
            keywords = st.text_input("Keywords", value="website development")
        with s2:
            max_results = st.number_input("Max results per provider", 5, 100, 50, step=5)
        platforms = st.multiselect(
            "Platforms",
            [status.name for status in statuses if status.name != "demo"],
            default=live_platforms,
            format_func=lambda name: next((s.label for s in statuses if s.name == name), name),
        )
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            min_budget = st.text_input("Minimum budget (optional)", placeholder="e.g. 15000")
        with f2:
            max_budget = st.text_input("Maximum budget (optional)", placeholder="e.g. 250000")
        with f3:
            currency = st.selectbox("Currency", ["Any", "INR", "USD", "EUR", "GBP", "CAD", "AUD"])
        with f4:
            project_type = st.selectbox("Project type", ["Any", "Fixed price", "Hourly", "Remote job"])
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            technologies = st.text_input("Required technologies", placeholder="wordpress, react, shopify")
        with t2:
            posted_days = st.number_input("Posted within days (0 = any)", 0, 365, 30)
        with t3:
            verified_only = st.checkbox("Verified open only")
        with t4:
            include_demo = st.checkbox("Include fictional demo listings (testing)")
        search_submitted = st.form_submit_button("Check for new opportunities", type="primary", width="stretch")

    if search_submitted:
        search = FreelanceSearch(
            keywords=keywords,
            platforms=platforms,
            min_budget=parse_number(min_budget),
            max_budget=parse_number(max_budget),
            currency="" if currency == "Any" else currency,
            project_type=project_type,
            technologies=technologies,
            posted_within_days=None if int(posted_days) == 0 else int(posted_days),
            verified_only=verified_only,
            max_results=int(max_results),
            include_demo=include_demo,
        )
        progress = st.progress(0.0)
        status_text = st.empty()

        def freelance_progress(stage: str, current: int, total: int, message: str) -> None:
            progress.progress(min(current / total, 1.0) if total else 0.1)
            status_text.caption(message)

        try:
            report = search_opportunities(
                db, settings, search,
                rules=settings.load_freelance_rules(),
                progress=freelance_progress,
            )
            st.session_state["freelance_report"] = report
            progress.progress(1.0)
            st.rerun()
        except Exception as exc:
            st.error(f"Freelance search failed: {type(exc).__name__}. See logs for details.")

    report = st.session_state.pop("freelance_report", None)
    if report is not None:
        st.success(report.summary())
        with st.expander("Search report and limitations", expanded=True):
            for message in report.provider_messages:
                st.write(f"- {message}")
            for limitation in report.limitations:
                st.write(f"- {limitation}")

    stats = db.freelance_stats()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stored opportunities", stats["total"])
    m2.metric("New since previous search", stats["new"])
    m3.metric("Verified open", stats["verified_open"])
    m4.metric("Demo samples", stats["demo"])
    st.caption(f"Last successful search: {db.get_meta('last_successful_freelance_search', 'never')}")

    ff1, ff2, ff3, ff4 = st.columns(4)
    with ff1:
        freelance_text = st.text_input("Search saved opportunities", key="fr_text")
    with ff2:
        platform_filter = st.multiselect("Platform filter", ["Freelancer.com", "Remotive (remote jobs)", "Arbeitnow (remote jobs)", "Upwork", "Demo (fictional)"], key="fr_platform")
    with ff3:
        status_filter = st.multiselect("Status filter", FREELANCE_STATUSES, key="fr_status")
    with ff4:
        min_match = st.slider("Minimum match score", 0, 100, 0, step=5, key="fr_min")
    ff5, ff6, ff7, ff8 = st.columns(4)
    with ff5:
        fr_min_budget = st.text_input("Saved min budget", key="fr_min_budget")
    with ff6:
        fr_max_budget = st.text_input("Saved max budget", key="fr_max_budget")
    with ff7:
        fr_currency = st.selectbox("Saved currency", ["Any", "INR", "USD", "EUR", "GBP", "CAD", "AUD"], key="fr_currency")
    with ff8:
        new_only = st.checkbox("New only", value=False, key="fr_new")
    include_demo_saved = st.checkbox("Include demo samples in saved results", value=False, key="fr_include_demo")

    opportunities = db.list_freelance(
        search=freelance_text,
        platforms=platform_filter or None,
        statuses=status_filter or None,
        min_score=min_match,
        min_budget=parse_number(fr_min_budget),
        max_budget=parse_number(fr_max_budget),
        currency="" if fr_currency == "Any" else fr_currency,
        new_only=new_only,
        include_demo=include_demo_saved,
        limit=500,
    )
    st.write(f"Showing **{len(opportunities)}** saved opportunity(ies).")
    if opportunities:
        rows = []
        for item in opportunities:
            rows.append({
                "New": "NEW" if item.get("is_new") else "",
                "Title": item.get("title", ""),
                "Platform": item.get("platform", ""),
                "Budget": (
                    f"{item.get('budget_min') or ''}–{item.get('budget_max') or ''} {item.get('currency') or ''}".strip("– ")
                    if (item.get("budget_min") is not None or item.get("budget_max") is not None)
                    else "Not disclosed"
                ),
                "Posted": (item.get("posted_at") or "")[:10] or "Unknown",
                "Proposals": item.get("proposal_count") if item.get("proposal_count") is not None else "Unknown",
                "Status": item.get("project_status", ""),
                "Match score": item.get("match_score", 0),
                "Last checked": (item.get("last_checked_at") or "")[:16],
                "URL": item.get("url", ""),
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={
                "URL": st.column_config.LinkColumn("Listing", display_text="Open"),
                "Match score": st.column_config.ProgressColumn("Match score", min_value=0, max_value=100, format="%d"),
            },
        )
        fr_options = {int(item["id"]): item for item in opportunities}
        selected_fr = st.selectbox(
            "Inspect an opportunity", list(fr_options.keys()),
            format_func=lambda value: f"{fr_options[value].get('title')} · {fr_options[value].get('platform')} · score {fr_options[value].get('match_score')}",
            key="fr_selected",
        )
        item = fr_options[selected_fr]
        st.markdown(f"### {item.get('title')}")
        st.write(f"Platform: **{item.get('platform')}** · Status: **{item.get('project_status')}** · Match: **{item.get('match_score')}/100**")
        if item.get("url"):
            st.link_button("Open original listing", item["url"], width="content")
        st.write(f"Budget: {item.get('budget_min')} – {item.get('budget_max')} {item.get('currency') or ''}".strip())
        st.write(f"Posted: {item.get('posted_at') or 'Unknown'} · Deadline: {item.get('deadline') or 'Not disclosed'}")
        st.write(f"Proposals: {item.get('proposal_count') if item.get('proposal_count') is not None else 'Not disclosed'}")
        st.write(f"Skills: {item.get('skills') or 'Not disclosed'}")
        st.write(f"Experience: {item.get('experience') or 'Not disclosed'}")
        st.write(f"Client: {item.get('client_info') or 'Not disclosed'}")
        st.write("**Description**")
        st.write(item.get("description") or "No description provided.")
        st.write("**Score explanation**")
        for note in (item.get("score_notes") or "").split("; "):
            if note:
                st.write(f"- {note}")
        st.caption("Applications and proposals must be reviewed and submitted manually. This tool never bids automatically.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        fe1, fe2 = st.columns(2)
        fe1.download_button(
            "Download CSV", data=export_freelance_csv(opportunities),
            file_name=f"mindsmiths_freelance_{stamp}.csv", mime="text/csv", width="stretch",
        )
        fe2.download_button(
            "Download Excel", data=export_freelance_excel(opportunities),
            file_name=f"mindsmiths_freelance_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    else:
        st.info("No saved opportunities match the filters. Run a live search or adjust the filters.")


# ---------------------------------------------------------------------------
# Tab 6: Sales CRM
# ---------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Sales CRM")
    metrics = db.crm_metrics()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total leads", metrics["total"])
    m2.metric("Qualified", metrics["qualified"])
    m3.metric("Contacted", metrics["contacted"])
    m4.metric("Reply rate", f"{metrics['reply_rate']}%" if metrics["reply_rate"] is not None else "No data")
    m5.metric("Quotations sent", metrics["quotations_sent"])
    m6, m7, m8, m9, m10 = st.columns(5)
    m6.metric("Deals won", metrics["won"])
    m7.metric("Conversion", f"{metrics['conversion_rate']}%" if metrics["conversion_rate"] is not None else "No data")
    m8.metric("Total quoted value", fmt_inr(metrics["total_quoted"]))
    m9.metric("Actual won value", fmt_inr(metrics["won_value"]))
    m10.metric("Lost", metrics["lost"])
    if metrics.get("sample_warning"):
        st.warning(metrics["sample_warning"])

    records = lead_records()
    if not records:
        st.info("No leads yet. Run a business discovery search or load the demo data first.")
    else:
        cities = sorted({record.get("city", "") for record in records if record.get("city")})
        categories = sorted({record.get("category", "") for record in records if record.get("category")})
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            crm_search = st.text_input("Search", key="crm_search")
        with f2:
            crm_status = st.multiselect("Status", CRM_STATUSES, key="crm_status")
        with f3:
            crm_city = st.multiselect("Location", cities, key="crm_city")
        with f4:
            crm_category = st.multiselect("Category", categories, key="crm_category")
        f5, f6, f7, f8 = st.columns(4)
        with f5:
            crm_web = st.multiselect("Website status", WEBSITE_STATUSES, key="crm_web")
        with f6:
            crm_budget = st.multiselect("Budget fit", BUDGET_FITS, key="crm_budget")
        with f7:
            crm_min_opp = st.slider("Minimum opportunity", 0, 100, 0, step=5, key="crm_min_opp")
        with f8:
            crm_follow_up = st.checkbox("Follow-up due (date set)", key="crm_follow")
        filtered = db.list_businesses(
            search=crm_search,
            statuses=crm_status or None,
            cities=crm_city or None,
            categories=crm_category or None,
            website_statuses=crm_web or None,
            budget_fits=crm_budget or None,
            min_opportunity_score=crm_min_opp if crm_min_opp else None,
            follow_up_only=crm_follow_up,
            follow_up_before=date.today().isoformat() if crm_follow_up else None,
            limit=1000,
        )
        st.write(f"Showing **{len(filtered)}** CRM lead(s).")
        if filtered:
            table = pd.DataFrame([
                {
                    "Business": record.get("name", ""),
                    "Status": record.get("status", ""),
                    "City": record.get("city", ""),
                    "Category": record.get("category", ""),
                    "Website": record.get("website_status", ""),
                    "Opportunity": record.get("opportunity_score", 0),
                    "Budget fit": record.get("budget_fit", ""),
                    "Follow-up": record.get("follow_up_date", ""),
                    "Quoted": record.get("quoted_amount"),
                    "Last contact": record.get("last_contact_date", ""),
                }
                for record in filtered
            ])
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "Opportunity": st.column_config.ProgressColumn("Opportunity", min_value=0, max_value=100, format="%d"),
                    "Quoted": st.column_config.NumberColumn("Quoted", format="₹%.0f"),
                },
            )
            options, mapping = lead_options(filtered)
            selected_id = st.selectbox(
                "Select a CRM lead", options,
                format_func=lambda value: f"{mapping[value].get('name')} · {mapping[value].get('status')}",
                key="crm_selected",
            )
            record = db.get_business(selected_id) or mapping[selected_id]
            st.markdown(f"### {record.get('name')}")
            st.caption(f"Lead source: {record.get('lead_source') or 'Not recorded'} · Opportunity: {record.get('opportunity_score', 0)}/100 · Budget fit: {record.get('budget_fit') or 'Unknown'}")
            with st.form(f"crm_form_{record['id']}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    status_value = st.selectbox(
                        "Status", CRM_STATUSES,
                        index=CRM_STATUSES.index(record["status"]) if record.get("status") in CRM_STATUSES else 0,
                    )
                with c2:
                    lead_source = st.text_input("Lead source", value=record.get("lead_source") or record.get("source") or "")
                with c3:
                    follow_up = st.text_input("Follow-up date (YYYY-MM-DD)", value=record.get("follow_up_date") or "")
                c4, c5, c6 = st.columns(3)
                with c4:
                    last_contact = st.text_input("Last contact date (YYYY-MM-DD)", value=record.get("last_contact_date") or "")
                with c5:
                    proposed = st.text_input("Proposed quotation (INR)", value="" if record.get("proposed_quotation") is None else str(record["proposed_quotation"]))
                with c6:
                    quoted = st.text_input("Actual quoted amount (INR)", value="" if record.get("quoted_amount") is None else str(record["quoted_amount"]))
                c7, c8 = st.columns(2)
                with c7:
                    client_budget = st.text_input("Client's stated budget (INR)", value="" if record.get("client_budget") is None else str(record["client_budget"]))
                with c8:
                    won_lost = st.text_input("Reason won/lost", value=record.get("won_lost_reason") or "")
                objections = st.text_area("Objections", value=record.get("objections") or "", height=80)
                crm_notes = st.text_area("Notes", value=record.get("notes") or "", height=100)
                saved = st.form_submit_button("Save CRM update", type="primary", width="stretch")
                if saved:
                    db.update_crm(record["id"], {
                        "status": status_value,
                        "lead_source": lead_source.strip(),
                        "follow_up_date": follow_up.strip(),
                        "last_contact_date": last_contact.strip(),
                        "proposed_quotation": parse_number(proposed),
                        "quoted_amount": parse_number(quoted),
                        "client_budget": parse_number(client_budget),
                        "won_lost_reason": won_lost.strip(),
                        "objections": objections.strip(),
                        "notes": crm_notes,
                    })
                    db.add_activity(record["id"], f"CRM updated. Status: {status_value}.", "crm")
                    st.session_state["flash_message"] = "CRM updated."
                    st.rerun()

            a1, a2 = st.columns(2)
            if a1.button("Log contact today", width="stretch", key="crm_log_contact"):
                db.update_crm(record["id"], {
                    "last_contact_date": date.today().isoformat(),
                    "status": record["status"] if record["status"] not in {"New lead", "new"} else "Contacted",
                })
                db.add_activity(record["id"], "Contact logged today.", "contact")
                st.session_state["flash_message"] = "Contact logged."
                st.rerun()
            with a2.form(f"activity_form_{record['id']}"):
                activity_note = st.text_input("Add an activity note", placeholder="Call summary, next step, objection...")
                add_activity = st.form_submit_button("Add note", width="stretch")
                if add_activity and activity_note.strip():
                    db.add_activity(record["id"], activity_note.strip(), "note")
                    st.session_state["flash_message"] = "Activity added."
                    st.rerun()

            activities = db.list_activities(record["id"])
            if activities:
                st.markdown("**Activity history**")
                st.dataframe(
                    pd.DataFrame([
                        {"When": item["created_at"], "Type": item["activity_type"], "Note": item["note"]}
                        for item in activities
                    ]),
                    hide_index=True, width="stretch", height=220,
                )
            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            ce1, ce2 = st.columns(2)
            ce1.download_button(
                "Export CRM CSV", data=export_csv(filtered),
                file_name=f"mindsmiths_crm_{stamp}.csv", mime="text/csv", width="stretch",
            )
            ce2.download_button(
                "Export CRM Excel", data=export_excel(filtered),
                file_name=f"mindsmiths_crm_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        else:
            st.info("No CRM leads match the filters.")


# ---------------------------------------------------------------------------
# Tab 7: Settings and data sources
# ---------------------------------------------------------------------------
with tabs[6]:
    st.subheader("Settings and data sources")
    st.markdown("#### Data sources and configuration")
    source_rows = [
        {"Source": "OpenStreetMap / Overpass", "Key required": "No", "State": "Available", "Notes": "Free public business data; coverage varies."},
        {"Source": "DuckDuckGo public search", "Key required": "No", "State": "Available / rate-limited", "Notes": "Public web presence search. Respects delays and fails gracefully."},
        {"Source": "SerpAPI Google Maps", "Key required": "SERPAPI_KEY", "State": "Configured" if settings.serpapi_key else "Configuration required", "Notes": "Optional paid service with a free tier."},
        {"Source": "Freelancer.com public API", "Key required": "No", "State": "Available", "Notes": "Active projects endpoint. Respect platform terms."},
        {"Source": "Remotive public API", "Key required": "No", "State": "Available", "Notes": "Remote jobs, not freelance projects."},
        {"Source": "Arbeitnow public API", "Key required": "No", "State": "Available", "Notes": "Remote jobs, not freelance projects."},
        {"Source": "Upwork API", "Key required": "UPWORK_ACCESS_TOKEN", "State": "Configured" if settings.upwork_access_token else "Configuration required", "Notes": "OAuth token required; no unauthenticated scraping."},
        {"Source": "PeoplePerHour / Guru", "Key required": "N/A", "State": "Manual only", "Notes": "No documented public API; the app does not scrape them."},
    ]
    st.dataframe(pd.DataFrame(source_rows), hide_index=True, width="stretch")
    st.caption(
        "Credentials are read from .env and are never displayed or exported. "
        "Never commit .env to version control."
    )

    st.markdown("#### Website opportunity weights")
    st.caption("These are configurable heuristics, not validated predictors of purchase intent.")
    with st.form("opportunity_rules_form"):
        r1, r2, r3 = st.columns(3)
        with r1:
            opp_no_website = st.number_input("No website listed", 0, 100, int(opportunity_rules.no_website))
            opp_website_problems = st.number_input("Website problems", 0, 100, int(opportunity_rules.website_problems))
            opp_recent = st.number_input("Recent verified activity", 0, 100, int(opportunity_rules.recent_activity))
        with r2:
            opp_audience = st.number_input("Verified audience", 0, 100, int(opportunity_rules.verified_audience))
            opp_scale = st.number_input("Multiple locations/catalogue", 0, 100, int(opportunity_rules.multiple_locations_or_catalogue))
            opp_promotes = st.number_input("Promotes services/bookings", 0, 100, int(opportunity_rules.promotes_services))
        with r3:
            opp_contact = st.number_input("Contact available", 0, 100, int(opportunity_rules.contact_available))
            opp_established = st.number_input("Established operations", 0, 100, int(opportunity_rules.established_operations))
            opp_expansion = st.number_input("Expansion/new branch", 0, 100, int(opportunity_rules.expansion))
        r4, r5, r6 = st.columns(3)
        with r4:
            opp_min_followers = st.number_input("Follower threshold", 0, 10_000_000, int(opportunity_rules.min_followers), step=500)
        with r5:
            opp_active_days = st.number_input("Active-within days", 1, 365, int(opportunity_rules.active_days))
        with r6:
            opp_catalogue_threshold = st.number_input("Catalogue threshold", 1, 10_000, int(opportunity_rules.catalogue_threshold))
        if st.form_submit_button("Save opportunity weights", width="stretch"):
            new_rules = OpportunityRules(
                no_website=int(opp_no_website),
                website_problems=int(opp_website_problems),
                recent_activity=int(opp_recent),
                verified_audience=int(opp_audience),
                multiple_locations_or_catalogue=int(opp_scale),
                promotes_services=int(opp_promotes),
                contact_available=int(opp_contact),
                established_operations=int(opp_established),
                expansion=int(opp_expansion),
                min_followers=int(opp_min_followers),
                active_days=int(opp_active_days),
                catalogue_threshold=int(opp_catalogue_threshold),
                high_threshold=int(opportunity_rules.high_threshold),
                potential_threshold=int(opportunity_rules.potential_threshold),
                low_threshold=int(opportunity_rules.low_threshold),
            )
            save_dataclass(settings.opportunity_rules_path, new_rules)
            st.session_state["flash_message"] = "Opportunity weights saved. Recalculate all scores to apply them."
            st.rerun()

    st.markdown("#### Freelance scoring and budget target")
    freelance_rules = settings.load_freelance_rules()
    with st.form("freelance_rules_form"):
        fr1, fr2, fr3 = st.columns(3)
        with fr1:
            fr_cap = st.number_input("Capability match", 0, 100, int(freelance_rules.capability_match))
            fr_budget = st.number_input("Budget suitability", 0, 100, int(freelance_rules.budget_suitability))
            fr_scope = st.number_input("Scope clarity", 0, 100, int(freelance_rules.scope_clarity))
        with fr2:
            fr_recent = st.number_input("Recency", 0, 100, int(freelance_rules.recency))
            fr_verified = st.number_input("Verified open", 0, 100, int(freelance_rules.verified_open))
            fr_competition = st.number_input("Low competition", 0, 100, int(freelance_rules.low_competition))
        with fr3:
            fr_effort = st.number_input("Manageable effort", 0, 100, int(freelance_rules.manageable_effort))
            fr_target_min = st.number_input("Target budget min (INR)", 0, 100_000_000, int(freelance_rules.target_budget_min), step=1000)
            fr_target_max = st.number_input("Target budget max (INR)", 0, 100_000_000, int(freelance_rules.target_budget_max), step=1000)
        if st.form_submit_button("Save freelance scoring", width="stretch"):
            from config import FreelanceRules

            save_dataclass(settings.freelance_rules_path, FreelanceRules(
                capability_match=int(fr_cap), budget_suitability=int(fr_budget),
                scope_clarity=int(fr_scope), recency=int(fr_recent),
                verified_open=int(fr_verified), low_competition=int(fr_competition),
                manageable_effort=int(fr_effort), target_budget_min=int(fr_target_min),
                target_budget_max=int(fr_target_max), default_currency="INR",
            ))
            st.session_state["flash_message"] = "Freelance scoring saved."
            st.rerun()

    st.markdown("#### Pricing catalogue")
    with st.form("pricing_form"):
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            min_price = st.number_input("Minimum project price", 0, 10_000_000, int(pricing_catalogue.minimum_project_price), step=500)
        with p2:
            max_price = st.number_input("Maximum project price", 0, 100_000_000, int(pricing_catalogue.maximum_project_price), step=1000)
        with p3:
            included_pages = st.number_input("Pages included", 1, 100, int(pricing_catalogue.included_pages))
        with p4:
            per_page = st.number_input("Price per extra page", 0, 1_000_000, int(pricing_catalogue.per_extra_page), step=250)
        st.markdown("**Base package prices**")
        base_cols = st.columns(len(WEBSITE_TYPES))
        new_base_prices: dict[str, int] = {}
        for column, key in zip(base_cols, WEBSITE_TYPES.keys()):
            with column:
                new_base_prices[key] = st.number_input(
                    WEBSITE_TYPES[key], 0, 10_000_000,
                    int(pricing_catalogue.base_prices.get(key, 0)), step=500, key=f"price_{key}",
                )
        st.markdown("**Feature prices**")
        feature_cols = st.columns(3)
        new_feature_prices: dict[str, int] = {}
        for index, (key, label) in enumerate(FEATURES.items()):
            with feature_cols[index % 3]:
                new_feature_prices[key] = st.number_input(
                    label, 0, 10_000_000,
                    int(pricing_catalogue.feature_prices.get(key, 0)), step=250, key=f"feature_{key}",
                )
        p5, p6, p7 = st.columns(3)
        with p5:
            maintenance = st.number_input("Maintenance per month", 0, 1_000_000, int(pricing_catalogue.maintenance_monthly), step=100)
        with p6:
            hosting = st.number_input("Hosting/domain per year", 0, 1_000_000, int(pricing_catalogue.hosting_domain_annual), step=500)
        with p7:
            validity = st.number_input("Quotation validity (days)", 1, 365, int(pricing_catalogue.validity_days))
        if st.form_submit_button("Save pricing catalogue", width="stretch"):
            pricing_catalogue.minimum_project_price = int(min_price)
            pricing_catalogue.maximum_project_price = int(max_price)
            pricing_catalogue.included_pages = int(included_pages)
            pricing_catalogue.per_extra_page = int(per_page)
            pricing_catalogue.base_prices = new_base_prices
            pricing_catalogue.feature_prices = new_feature_prices
            pricing_catalogue.maintenance_monthly = int(maintenance)
            pricing_catalogue.hosting_domain_annual = int(hosting)
            pricing_catalogue.validity_days = int(validity)
            save_catalogue(settings.pricing_catalogue_path, pricing_catalogue)
            st.session_state["flash_message"] = "Pricing catalogue saved."
            st.rerun()

    st.markdown("#### Data quality and maintenance")
    evidence_summary = db.evidence_summary()
    q1, q2, q3 = st.columns(3)
    q1.metric("Evidence fields", evidence_summary["fields"])
    q2.metric("Leads with evidence", evidence_summary["businesses"])
    q3.metric("Verified evidence", evidence_summary["verified"])
    st.caption(
        "Unverified values are never presented as facts. Social matches and search snippets remain unverified until confirmed."
    )
    d1, d2, d3 = st.columns(3)
    if d1.button("Back up database", width="stretch", key="settings_backup"):
        path = db.backup(settings.data_dir)
        st.session_state["flash_message"] = f"Backup created: {path}"
        st.rerun()
    if d2.button("Retry failed website checks", width="stretch", key="settings_retry"):
        failed = [
            record for record in db.list_businesses(limit=100000, include_excluded=True)
            if record.get("website_status") in {"Website unreachable", "Website check failed"}
        ]
        progress = st.progress(0.0)
        refreshed = 0
        for index, record in enumerate(failed, start=1):
            try:
                check = audit_website(record.get("website"), settings=settings, contact_page=record.get("contact_page") or "")
                db.update_audit(record["id"], status=check.status, report_json=check.to_json(), error=check.error)
                db.update_business_fields(record["id"], {
                    "website_status": check.status,
                    "website_response_ms": check.response_time_ms,
                    "website_page_bytes": check.page_size_bytes,
                    "has_booking": check.has_booking,
                    "has_enquiry": check.has_enquiry,
                    "has_cta": check.has_cta,
                })
                updated = db.get_business(record["id"])
                if updated:
                    record_business_evidence(db, record["id"], updated)
                    save_analysis(updated, opportunity_rules)
                refreshed += 1
            except Exception:
                continue
            progress.progress(index / max(1, len(failed)))
        st.session_state["flash_message"] = f"Retried {refreshed} failed website check(s)."
        st.rerun()
    if d3.button("Recompute all intelligence", width="stretch", key="settings_recompute"):
        for record in db.list_businesses(limit=100000, include_excluded=True):
            save_analysis(record, opportunity_rules)
        st.session_state["flash_message"] = "Recomputed revenue and opportunity intelligence for all leads."
        st.rerun()

    st.markdown("#### Duplicate review")
    groups = db.duplicate_candidates()
    if not groups:
        st.caption("No obvious duplicate groups found by phone or domain.")
    else:
        st.caption("Groups share a phone number or domain. Review before merging; the kept record preserves non-empty values.")
        group_labels = [f"{item['names']} ({item['n']} records)" for item in groups]
        selected_group = st.selectbox("Duplicate group", group_labels, key="dup_group")
        group = groups[group_labels.index(selected_group)]
        ids = [int(value) for value in str(group["ids"]).split(",") if value.strip()]
        keep_id = st.selectbox("Record to keep", ids, format_func=lambda value: f"#{value} · {db.get_business(value).get('name')}", key="dup_keep")
        merge_id = st.selectbox("Record to merge into the kept record", [value for value in ids if value != keep_id], key="dup_merge")
        if st.button("Merge selected duplicates", width="stretch", key="dup_merge_button"):
            if db.merge_businesses(int(keep_id), int(merge_id)):
                st.session_state["flash_message"] = "Duplicate records merged."
                st.rerun()

    st.markdown("#### Outreach assistant")
    st.caption(
        "Draft messages from verified evidence. Nothing is sent automatically. Save approved drafts to the CRM."
    )
    records = lead_records()
    if records:
        options, mapping = lead_options(records)
        selected_id = st.selectbox(
            "Select a lead for outreach", options,
            format_func=lambda value: lead_label(mapping[value]), key="outreach_selected",
        )
        record = db.get_business(selected_id) or mapping[selected_id]
        _, opportunity = analysis_for(record, opportunity_rules)
        o1, o2, o3 = st.columns(3)
        with o1:
            channel = st.selectbox("Channel", CHANNELS, key="outreach_channel")
        with o2:
            tone = st.selectbox("Tone", TONES, key="outreach_tone")
        with o3:
            offer = st.selectbox("Offer", OFFERS, key="outreach_offer")
        draft = generate_outreach(record, opportunity, channel=channel, tone=tone, offer=offer)
        if draft.subject:
            st.text_input("Subject", value=draft.subject, key="outreach_subject")
        st.text_area("Draft message", value=draft.body, height=260, key="outreach_body")
        st.caption(f"Observation used: {draft.observation}")
        st.code(draft.body, language=None)
        st.caption("Copy the code block above, or use your system clipboard after selecting the text.")
        oc1, oc2 = st.columns(2)
        if oc1.button("Save approved draft to CRM", width="stretch", key="outreach_save"):
            db.save_outreach_draft(
                record["id"], channel=channel, tone=tone, offer=offer,
                subject=draft.subject, body=draft.body, approved=True,
            )
            db.add_activity(record["id"], f"Approved {channel} outreach draft saved.", "outreach")
            st.session_state["flash_message"] = "Approved outreach draft saved to the CRM."
            st.rerun()
        if oc2.button("Mark lead contacted", width="stretch", key="outreach_contacted"):
            db.update_crm(record["id"], {
                "status": "Contacted",
                "last_contact_date": date.today().isoformat(),
            })
            db.add_activity(record["id"], f"Marked contacted after preparing {channel} outreach.", "outreach")
            st.session_state["flash_message"] = "Lead marked contacted."
            st.rerun()
        drafts = db.list_outreach_drafts(record["id"], limit=5)
        if drafts:
            with st.expander("Saved outreach drafts"):
                for item in drafts:
                    st.markdown(f"**{item['channel']} · {item['tone']} · {item['created_at']}**")
                    if item.get("subject"):
                        st.write(f"Subject: {item['subject']}")
                    st.write(item["body"])
                    st.divider()
    else:
        st.info("No leads available for outreach.")


st.divider()
st.caption(
    "MindSmiths Sales Intelligence · MindSmiths, backed by Melouz Technologies Pvt Ltd · "
    "Local-first SQLite storage · Public data only · Scores are prioritisation signals, not purchase-intent facts · "
    "No unsolicited automated messaging."
)
