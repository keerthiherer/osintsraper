"""Website checks, contact extraction and social-link enrichment."""
from __future__ import annotations

import time
from urllib.parse import urlparse

from config import (
    Settings,
    WEBSITE_CHECK_FAILED,
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
)
from .contacts import extract_contacts
from .models import Business, SocialProfile
from .presence import discover_presence
from .social import extract_social_links
from .website import check_website, fetch_html


def _merge_socials(business: Business, found: list[SocialProfile]) -> None:
    existing = {social.platform: social for social in business.socials}
    for social in found:
        current = existing.get(social.platform)
        if current is None:
            existing[social.platform] = social
            continue
        if social.followers is not None and (
            current.followers is None or social.followers_verified
        ):
            current.followers = social.followers
            current.followers_verified = social.followers_verified
        if social.last_active and (social.activity_verified or not current.activity_verified):
            current.last_active = social.last_active
            current.activity_verified = social.activity_verified
        current.confidence = max(current.confidence, social.confidence)
        if social.source == "website" and current.source != "website":
            current.source = "website"
    business.socials = list(existing.values())


def _apply_presence(business: Business, settings: Settings, *, client=None) -> None:
    presence = discover_presence(business, settings, client=client)
    _merge_socials(business, presence.socials)
    if not business.website and presence.website:
        business.website = presence.website
        business.website_source = presence.website_source
    if not business.phone and presence.phone:
        business.phone = presence.phone
        business.phone_source = presence.phone_source
    if not business.email and presence.email:
        business.email = presence.email
        business.email_source = presence.email_source


def enrich_business(business: Business, settings: Settings, *, delay: bool = True) -> Business:
    if business.source == "demo":
        return business
    if delay and settings.request_delay:
        time.sleep(max(0.0, settings.request_delay))

    presence_done = False
    if not business.website and settings.web_search_enabled:
        _apply_presence(business, settings)
        presence_done = True

    if not business.website:
        business.website_status = WEBSITE_NO_WEBSITE
        return business

    check = check_website(
        business.website,
        timeout=settings.request_timeout,
        user_agent=settings.user_agent,
    )
    business.website_status = check.status
    business.website_http_status = check.http_status
    business.website_final_url = check.final_url
    business.website_title = check.title
    business.website_issues = list(check.issues)

    if check.status != WEBSITE_REACHABLE or not check.html:
        if check.status == WEBSITE_CHECK_FAILED and not business.website_issues:
            business.website_issues = ["Website check failed"]
        return business

    _merge_socials(business, extract_social_links(check.html, check.final_url or business.website, business.name))
    contacts = extract_contacts(check.html, check.final_url or business.website)
    if not business.email and contacts.emails:
        business.email = contacts.emails[0]
        business.email_source = "website"
    if not business.phone and contacts.phones:
        business.phone = contacts.phones[0]
        business.phone_source = "website"
    business.contact_page = business.contact_page or contacts.contact_page
    business.form_url = business.form_url or contacts.form_url

    # One extra lightweight request when the homepage lacks email or phone.
    contact_url = contacts.contact_page
    if (not business.email or not business.phone) and contact_url and contact_url != (check.final_url or business.website):
        allowed = {urlparse(check.final_url or business.website).netloc.lower()}
        if urlparse(contact_url).netloc.lower() in allowed:
            if settings.request_delay:
                time.sleep(max(0.0, settings.request_delay))
            contact_html = fetch_html(
                contact_url,
                timeout=settings.request_timeout,
                user_agent=settings.user_agent,
            )
            if contact_html:
                extra = extract_contacts(contact_html, contact_url)
                if extra.emails and not business.email:
                    business.email = extra.emails[0]
                    business.email_source = "website"
                if not business.phone and extra.phones:
                    business.phone = extra.phones[0]
                    business.phone_source = "website"
                business.form_url = business.form_url or extra.form_url
                _merge_socials(business, extract_social_links(contact_html, contact_url, business.name))

    if not presence_done and settings.web_search_enabled:
        platforms = {social.platform for social in business.socials}
        if not {"instagram", "facebook"}.issubset(platforms):
            _apply_presence(business, settings)
    return business
