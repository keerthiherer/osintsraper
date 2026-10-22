"""Extract publicly displayed business contact details from a website."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import clean_text, normalize_phone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().\-]{7,}\d)")
BAD_EMAIL_PARTS = (
    "example.com", "sentry.io", "sentry-next", "wixpress.com", "domain.com",
    "email.com", "yourdomain", "company.com", "sentry.wixpress", "godaddy.com",
    "squarespace.com", "wordpress.com", "wix.com", "cloudflare.com",
)
BAD_EMAIL_PREFIXES = (
    "noreply", "no-reply", "donotreply", "support@sentry", "privacy@",
    "filler@", "test@", "sample@", "yourname@", "your.email@", "name@", "email@",
)
CONTACT_WORDS = (
    "contact", "contact-us", "contactus", "get-in-touch", "getintouch",
    "enquiry", "enquiries", "reach-us", "reachus", "book-now", "connect",
)


@dataclass
class ContactDetails:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    contact_page: str = ""
    form_url: str = ""


def is_business_email(email: str) -> bool:
    email = email.lower().strip(".,;:()<>\"'")
    if any(part in email for part in BAD_EMAIL_PARTS):
        return False
    if email.startswith(BAD_EMAIL_PREFIXES):
        return False
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", email):
        return False
    return True


def _same_domain(url: str, base_url: str) -> bool:
    try:
        a = urlparse(url).netloc.lower().removeprefix("www.")
        b = urlparse(base_url).netloc.lower().removeprefix("www.")
    except ValueError:
        return False
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def _jsonld_values(value, target_key: str) -> list:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == target_key:
                found.append(item)
            else:
                found.extend(_jsonld_values(item, target_key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_jsonld_values(item, target_key))
    return found


def extract_contacts(html: str, base_url: str) -> ContactDetails:
    details = ContactDetails()
    if not html:
        return details
    soup = BeautifulSoup(html, "html.parser")

    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.lower().startswith("mailto:"):
            candidates.extend(re.split(r"[,;?]", href[7:]))
        elif href.lower().startswith("tel:"):
            phone = clean_text(href[4:])
            if normalize_phone(phone):
                details.phones.append(phone)

    text = soup.get_text(" ", strip=True)
    candidates.extend(EMAIL_RE.findall(text))

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for email in _jsonld_values(payload, "email"):
            if isinstance(email, str):
                candidates.append(email.replace("mailto:", ""))
        for phone in _jsonld_values(payload, "telephone"):
            if isinstance(phone, str) and normalize_phone(phone):
                details.phones.append(clean_text(phone))
    for email in candidates:
        email = email.strip().strip(".,;:()<>\"'").lower()
        if is_business_email(email) and email not in details.emails:
            details.emails.append(email)

    if not details.phones:
        for match in PHONE_RE.findall(text):
            if normalize_phone(match):
                details.phones.append(clean_text(match))
                break
    details.phones = details.phones[:3]
    details.emails = details.emails[:5]

    best_contact = ""
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        label = f"{anchor.get_text(' ', strip=True)} {href}".lower()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        if any(word in label for word in CONTACT_WORDS):
            url = urljoin(base_url, href)
            if _same_domain(url, base_url):
                best_contact = url
                break
    details.contact_page = best_contact

    form = soup.find("form")
    if form is not None:
        action = (form.get("action") or "").strip()
        form_url = urljoin(base_url, action) if action else best_contact or base_url
        if _same_domain(form_url, base_url):
            details.form_url = form_url
    elif best_contact:
        details.form_url = best_contact
    return details
