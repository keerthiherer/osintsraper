"""Lightweight, non-invasive website health checks."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    WEBSITE_CHECK_FAILED,
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
)
from .models import normalize_website

log = logging.getLogger(__name__)
MAX_BYTES = 1_000_000


@dataclass
class WebsiteCheck:
    status: str
    url: str = ""
    http_status: int | None = None
    final_url: str = ""
    title: str = ""
    meta_description: str = ""
    has_viewport: bool = False
    https: bool = False
    issues: list[str] = field(default_factory=list)
    html: str = ""
    error: str = ""
    page_text_length: int = 0
    response_time_ms: int | None = None
    page_size_bytes: int | None = None
    has_cta: bool | None = None
    has_contact_details: bool | None = None
    has_enquiry_form: bool | None = None
    has_booking_hint: bool | None = None


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def parse_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())
    meta = soup.find("meta", attrs={"name": "description"})
    description = ""
    if meta and meta.get("content"):
        description = " ".join(meta["content"].split())
    viewport = soup.find("meta", attrs={"name": "viewport"})
    has_enquiry_form = soup.find("form") is not None
    hrefs = " ".join(anchor.get("href", "") for anchor in soup.find_all("a", href=True)).lower()
    raw_text = " ".join(soup.get_text(" ", strip=True).split())
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    lowered = text.lower()
    has_cta = bool(re.search(
        r"\b(contact us|get in touch|book now|enquire|enquiry|get a quote|request a quote|"
        r"call us|whatsapp|buy now|shop now|send message|schedule|appointment)\b",
        lowered,
    ))
    has_contact_details = bool(
        re.search(r"mailto:|tel:", hrefs)
        or re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", raw_text)
        or re.search(r"(?:\+?\d[\d\s().\-]{7,}\d)", raw_text)
    )
    has_booking_hint = bool(re.search(
        r"\b(book(?:ing)?|reserve|reservation|appointment|schedule a|consultation)\b",
        lowered,
    ))
    return {
        "title": title[:300],
        "meta_description": description[:500],
        "has_viewport": viewport is not None,
        "text": text,
        "text_length": len(text),
        "has_cta": has_cta,
        "has_contact_details": has_contact_details,
        "has_enquiry_form": has_enquiry_form,
        "has_booking_hint": has_booking_hint,
    }


def check_website(
    url: str | None,
    *,
    timeout: int = 15,
    session: requests.Session | None = None,
    user_agent: str = "MindSmithsLeadIntelligence/1.0",
) -> WebsiteCheck:
    raw = (url or "").strip()
    if not raw:
        return WebsiteCheck(status=WEBSITE_NO_WEBSITE)
    normalized = normalize_website(raw)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return WebsiteCheck(status=WEBSITE_CHECK_FAILED, url=normalized, error="Invalid URL")

    owns_session = session is None
    session = session or build_session()
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-IN,en;q=0.8",
    }
    check = WebsiteCheck(status=WEBSITE_CHECK_FAILED, url=normalized, https=parsed.scheme == "https")
    started = time.monotonic()
    try:
        response = session.get(
            normalized,
            headers=headers,
            timeout=(5, timeout),
            allow_redirects=True,
            stream=True,
        )
        check.http_status = response.status_code
        check.final_url = response.url
        check.https = urlparse(response.url).scheme == "https"

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_BYTES:
                break
        response.close()
        check.response_time_ms = int((time.monotonic() - started) * 1000)
        check.page_size_bytes = total
        body = b"".join(chunks)
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        try:
            html = body.decode(encoding, errors="replace")
        except (LookupError, TypeError):
            html = body.decode("utf-8", errors="replace")
        check.html = html

        if response.status_code >= 400:
            check.status = WEBSITE_UNREACHABLE
            check.issues.append(f"HTTP {response.status_code}")
            check.error = f"HTTP {response.status_code}"
            return check

        check.status = WEBSITE_REACHABLE
        page = parse_page(html)
        check.title = page["title"]
        check.meta_description = page["meta_description"]
        check.has_viewport = page["has_viewport"]
        check.page_text_length = page["text_length"]
        check.has_cta = page["has_cta"]
        check.has_contact_details = page["has_contact_details"]
        check.has_enquiry_form = page["has_enquiry_form"]
        check.has_booking_hint = page["has_booking_hint"]

        if not check.title:
            check.issues.append("Missing page title")
        if not check.meta_description:
            check.issues.append("Missing meta description")
        if not check.has_viewport:
            check.issues.append("Missing mobile viewport")
        if not check.https:
            check.issues.append("HTTPS not used")
        if page["text_length"] < 200:
            check.issues.append("Minimal page content")
        return check
    except requests.exceptions.SSLError as exc:
        check.status = WEBSITE_UNREACHABLE
        check.issues.append("TLS/SSL certificate error")
        check.error = "TLS/SSL certificate error"
        log.info("TLS error while checking %s: %s", normalized, type(exc).__name__)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        check.status = WEBSITE_UNREACHABLE
        check.issues.append("Connection failed or timed out")
        check.error = "Connection failed or timed out"
        log.info("Connection error while checking %s: %s", normalized, type(exc).__name__)
    except requests.exceptions.InvalidURL:
        check.status = WEBSITE_CHECK_FAILED
        check.error = "Invalid URL"
    except Exception as exc:  # defensive: never let one site stop a search
        check.status = WEBSITE_CHECK_FAILED
        check.error = f"Check failed: {type(exc).__name__}"
        log.warning("Unexpected website check error for %s: %s", normalized, type(exc).__name__)
    finally:
        if owns_session:
            session.close()
    return check


def fetch_html(
    url: str,
    *,
    timeout: int = 15,
    session: requests.Session | None = None,
    user_agent: str = "MindSmithsLeadIntelligence/1.0",
) -> str:
    owns_session = session is None
    session = session or build_session()
    try:
        response = session.get(
            normalize_website(url),
            headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"},
            timeout=(5, timeout),
            allow_redirects=True,
            stream=True,
        )
        if response.status_code >= 400:
            response.close()
            return ""
        chunks, total = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_BYTES:
                break
        response.close()
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        try:
            return b"".join(chunks).decode(encoding, errors="replace")
        except (LookupError, TypeError):
            return b"".join(chunks).decode("utf-8", errors="replace")
    except requests.RequestException:
        return ""
    finally:
        if owns_session:
            session.close()
