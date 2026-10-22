"""Public web-presence discovery for social links, phones and emails.

Uses public search results (DuckDuckGo HTML) or SerpAPI's Google engine when a
key is configured. It never logs into social platforms, bypasses a login wall,
or scrapes private data.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup

from config import Settings
from .contacts import EMAIL_RE, is_business_email
from .models import Business, SocialProfile, clean_text, normalize_phone
from .social import SKIP_PATHS, normalize_social_url, platform_from_url

log = logging.getLogger(__name__)

DIRECTORY_DOMAINS = {
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com", "yellowpages.com",
    "yelp.com", "zomato.com", "swiggy.com", "practo.com", "urbanclap.com", "urbancompany.com",
    "linktr.ee", "wa.me", "whatsapp.com", "google.com", "goo.gl", "maps.app.goo.gl",
    "wikipedia.org", "youtube.com", "youtu.be", "pinterest.com", "twitter.com", "x.com",
    "tumblr.com", "threads.net", "behance.net", "dribbble.com", "foursquare.com",
    "tripadvisor.com", "facebook.com", "instagram.com", "linkedin.com", "amazon.in",
    "amazon.com", "flipkart.com", "quora.com", "reddit.com", "medium.com", "blogspot.com",
    "wordpress.com", "sites.google.com", "business.site", "weebly.com", "wixsite.com",
    "contactout.com", "rocketreach.co", "zoominfo.com", "apollo.io", "signalhire.com",
    "lusha.com", "findby.in", "marriagecolours.com", "weddingbazaar.com", "wedmegood.com",
    "shaadisaga.com", "yellowpages.in", "cybo.com", "bizapedia.com", "opencorporates.com",
    "worldplaces.me", "deldure.com", "petalokasi.org", "vkno.in", "mapy.com", "magicpin.in",
    "webindia123.com", "theweddingcompany.com", "weddingwire.in", "bizzbuzz.in",
    "shopify.com", "mystrikingly.com", "godaddysites.com", "web.app", "firebaseapp.com",
}

GENERIC_NAME_TOKENS = {
    "the", "and", "for", "studio", "studios", "photography", "photo", "photos", "digital",
    "salon", "spa", "beauty", "clinic", "interiors", "interior", "design", "designs",
    "events", "event", "wedding", "weddings", "cafe", "restaurant", "academy", "institute",
    "coaching", "centre", "center", "services", "service", "solutions", "company",
    "consulting", "consultants", "boutique", "jewellery", "jewelry", "fitness", "gym",
    "hotel", "resort", "school", "college", "shop", "store", "world", "india", "chennai",
}

PHONE_RE = re.compile(r"(?<![\d/])(?:\+?91[\s\-]?)?[6-9](?:[\s\-]?\d){9}(?![\d/])")
FOLLOWER_RE = re.compile(r"([\d][\d,.]*)\s*([KMB])?\s*\+?\s*followers?", re.IGNORECASE)

_rate_lock = threading.Lock()
_last_search = 0.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "duckduckgo"


@dataclass
class PresenceResult:
    socials: list[SocialProfile] = field(default_factory=list)
    website: str = ""
    website_source: str = ""
    phone: str = ""
    phone_source: str = ""
    email: str = ""
    email_source: str = ""
    notes: list[str] = field(default_factory=list)


def _respect_rate_limit(delay: float) -> None:
    global _last_search
    with _rate_lock:
        wait = (_last_search + delay) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_search = time.monotonic()


def _decode_ddg_link(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return href


class WebSearchClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.8",
        })

    def search(self, query: str) -> list[SearchResult]:
        engine = self.settings.web_search_engine
        if engine in {"auto", "serpapi"} and self.settings.serpapi_key:
            try:
                results = self._serpapi(query)
                if results or engine == "serpapi":
                    return results
            except Exception as exc:
                log.info("SerpAPI web search failed (%s); trying DuckDuckGo", type(exc).__name__)
        if engine == "serpapi":
            return []
        return self._duckduckgo(query)

    def _serpapi(self, query: str) -> list[SearchResult]:
        _respect_rate_limit(self.settings.web_search_delay)
        try:
            response = self.session.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": query,
                    "num": self.settings.web_search_results,
                    "hl": "en",
                    "gl": "in",
                    "api_key": self.settings.serpapi_key,
                },
                timeout=max(20, self.settings.request_timeout),
            )
            if response.status_code >= 400:
                return []
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []
        results = []
        for item in payload.get("organic_results", [])[: self.settings.web_search_results]:
            link = clean_text(item.get("link"))
            if link:
                results.append(SearchResult(
                    title=clean_text(item.get("title")),
                    url=link,
                    snippet=clean_text(item.get("snippet")),
                    source="serpapi_google",
                ))
        return results

    def _duckduckgo(self, query: str) -> list[SearchResult]:
        _respect_rate_limit(self.settings.web_search_delay)
        try:
            response = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                timeout=max(20, self.settings.request_timeout),
            )
        except requests.RequestException as exc:
            log.info("Public web search failed: %s", type(exc).__name__)
            response = None
        if response is not None and response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            for block in soup.select("div.result")[: self.settings.web_search_results]:
                anchor = block.select_one("a.result__a")
                if anchor is None:
                    continue
                url = _decode_ddg_link(anchor.get("href", ""))
                snippet_el = block.select_one(".result__snippet")
                results.append(SearchResult(
                    title=clean_text(anchor.get_text(" ", strip=True)),
                    url=url,
                    snippet=clean_text(snippet_el.get_text(" ", strip=True) if snippet_el else ""),
                    source="duckduckgo",
                ))
            if results:
                return results
        elif response is not None:
            log.info("Public web search returned HTTP %s; using reader fallback", response.status_code)
        return self._reader_fallback(query)

    def _reader_fallback(self, query: str) -> list[SearchResult]:
        """Use a public page reader when the search endpoint rate-limits this IP."""
        target = "https://html.duckduckgo.com/html/?q=" + quote(query)
        try:
            response = requests.get(
                "https://r.jina.ai/" + target,
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept": "text/plain",
                },
                timeout=max(45, self.settings.request_timeout * 3),
            )
        except requests.RequestException as exc:
            log.info("Reader fallback failed: %s", type(exc).__name__)
            return []
        if response.status_code != 200:
            log.info("Reader fallback returned HTTP %s", response.status_code)
            return []
        return self._parse_reader_markdown(response.text)

    def _parse_reader_markdown(self, text: str) -> list[SearchResult]:
        results = []
        sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
        for section in sections:
            match = re.match(r"## \[(.+?)\]\((.+?)\)", section)
            if not match:
                continue
            title = clean_text(match.group(1))
            url = _decode_ddg_link(match.group(2).strip())
            body = section[match.end():]
            body = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
            body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
            body = re.sub(r"[#*`>|]", " ", body)
            snippet = clean_text(body)
            if not url or not title:
                continue
            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet[:1200],
                source="duckduckgo_reader",
            ))
            if len(results) >= self.settings.web_search_results:
                break
        return results


def _name_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _name_tokens(name: str) -> list[str]:
    tokens = []
    for raw in re.findall(r"[A-Za-z0-9]+", name or ""):
        token = raw.lower()
        if len(token) >= 2 and token not in GENERIC_NAME_TOKENS:
            tokens.append(token)
    return tokens


def _location_terms(business: Business) -> list[str]:
    terms = []
    for value in (business.locality, business.city):
        slug = _name_slug(value)
        if len(slug) >= 3 and slug not in terms:
            terms.append(slug)
    return terms


def _location_match(business: Business, combined: str, url_slug: str) -> bool:
    return any(term in combined or term in url_slug for term in _location_terms(business))


def _match_confidence(result: SearchResult, business: Business) -> float:
    name_slug = _name_slug(business.name)
    combined = _name_slug(f"{result.title} {result.snippet}")
    url_slug = _name_slug(result.url)
    path_slug = _name_slug(urlparse(result.url).path)
    exact_handle = bool(name_slug) and path_slug in {name_slug, "in" + name_slug, "company" + name_slug}
    location = _location_match(business, combined, url_slug)
    if len(name_slug) >= 5 and (name_slug in combined or name_slug in url_slug):
        if location or exact_handle or not _location_terms(business):
            return 0.9
        return 0.6
    tokens = _name_tokens(business.name)
    matched = [token for token in tokens if token in combined or token in url_slug]
    if not tokens or not matched:
        return 0.0
    if len(matched) == len(tokens):
        if len(tokens) > 1:
            return 0.9 if location else 0.78
        return 0.5
    if len(matched) >= 2 and location:
        return 0.75
    return 0.0


def _parse_followers(text: str) -> int | None:
    match = FOLLOWER_RE.search(text or "")
    if not match:
        return None
    number_text = match.group(1).replace(",", "")
    try:
        number = float(number_text)
    except ValueError:
        return None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        (match.group(2) or "").upper(), 1
    )
    return int(number * multiplier)


def _host_is_directory(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == blocked or host.endswith("." + blocked) for blocked in DIRECTORY_DOMAINS)


def _website_candidate(results: list[SearchResult], business: Business) -> str:
    name_slug = _name_slug(business.name)
    tokens = _name_tokens(business.name)
    for result in results:
        url = result.url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if platform_from_url(url) or _host_is_directory(url):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|webp|svg|zip)$", parsed.path, re.I):
            continue
        host_slug = _name_slug(parsed.netloc)
        if len(name_slug) >= 5 and name_slug in host_slug:
            remainder = host_slug.replace(name_slug, "", 1)
            if _match_confidence(result, business) >= 0.7 or remainder in {
                "com", "in", "net", "org", "co", "coin", "studio", "photography",
            }:
                return f"{parsed.scheme}://{parsed.netloc}/"
        if _match_confidence(result, business) < 0.75:
            continue
        matched = [token for token in tokens if token in host_slug]
        if len(matched) >= 2:
            return f"{parsed.scheme}://{parsed.netloc}/"
    return ""


def _extract_socials(results: list[SearchResult], business: Business) -> list[SocialProfile]:
    best: dict[str, SocialProfile] = {}
    for result in results:
        confidence = _match_confidence(result, business)
        if confidence < 0.7:
            continue
        platform = platform_from_url(result.url)
        if not platform:
            continue
        path_parts = [part.lower() for part in urlparse(result.url).path.split("/") if part]
        if path_parts and path_parts[0] in SKIP_PATHS.get(platform, set()):
            continue
        url = normalize_social_url(result.url, platform)
        if not url:
            continue
        text = f"{result.title} {result.snippet}"
        followers = _parse_followers(text)
        candidate = SocialProfile(
            platform=platform,
            url=url,
            followers=followers,
            followers_verified=False,
            activity_verified=False,
            last_active=None,
            confidence=round(min(confidence, 0.9), 2),
            source=result.source,
        )
        current = best.get(platform)
        if current is None:
            best[platform] = candidate
        else:
            current.confidence = max(current.confidence, candidate.confidence)
            if current.followers is None and candidate.followers is not None:
                current.followers = candidate.followers
    return list(best.values())


def _extract_contact(
    results: list[SearchResult],
    business: Business,
    website: str,
    platform_urls: set[str],
) -> tuple[str, str, str, str]:
    phone, phone_source, email, email_source = "", "", "", ""
    for result in results:
        if _match_confidence(result, business) < 0.7:
            continue
        trusted = (
            platform_from_url(result.url) != ""
            or (website and result.url.rstrip("/") == website.rstrip("/"))
            or (website and urlparse(result.url).netloc == urlparse(website).netloc)
        )
        if not trusted:
            continue
        text = f"{result.title} {result.snippet}"
        if not phone:
            match = PHONE_RE.search(text)
            if match and normalize_phone(match.group(0)):
                phone = clean_text(match.group(0))
                phone_source = result.source
        if not email:
            for address in EMAIL_RE.findall(text):
                if is_business_email(address):
                    email = address.lower()
                    email_source = result.source
                    break
        if phone and email:
            break
    return phone, phone_source, email, email_source


def discover_presence(business: Business, settings: Settings, client: WebSearchClient | None = None) -> PresenceResult:
    if not settings.web_search_enabled:
        return PresenceResult()
    client = client or WebSearchClient(settings)
    location = business.locality or business.city
    query = f'"{business.name}" {location} instagram facebook linkedin'.strip()
    results = client.search(query)
    if not results:
        return PresenceResult(notes=["No public web search results found."])

    socials = _extract_socials(results, business)
    website = _website_candidate(results, business)
    if not website:
        contact_results = client.search(f'"{business.name}" {location} email phone'.strip())
        if contact_results:
            results.extend(contact_results)
            socials = _extract_socials(results, business)
            website = _website_candidate(results, business)

    platforms = {social.platform for social in socials}
    missing = [name for name in ("instagram", "facebook") if name not in platforms]
    if missing:
        social_results = client.search(
            f'"{business.name}" {location} ' + " ".join(missing)
        )
        if social_results:
            results.extend(social_results)
            socials = _extract_socials(results, business)
    website_source = "public_web_search" if website else ""
    platform_urls = {social.url for social in socials}
    phone, phone_source, email, email_source = _extract_contact(
        results, business, website, platform_urls
    )
    return PresenceResult(
        socials=socials,
        website=website,
        website_source=website_source,
        phone=phone,
        phone_source=phone_source,
        email=email,
        email_source=email_source,
        notes=[
            "Contact and social data may come from public search results; verify before outreach."
        ] if (socials or phone or email) else [],
    )
