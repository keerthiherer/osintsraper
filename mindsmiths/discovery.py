"""Business discovery providers: SerpAPI, OpenStreetMap/Overpass and demo data."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from config import Settings
from .models import (
    Business,
    SocialProfile,
    clean_text,
    normalize_phone,
    normalize_website,
    now_iso,
    parse_float,
    parse_int,
    slug,
)

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


class DiscoveryError(RuntimeError):
    pass


@dataclass
class SearchParams:
    city: str
    locality: str = ""
    category: str = ""
    keywords: str = ""
    max_results: int = 40
    provider: str = "openstreetmap"
    min_followers: int = 2000
    active_days: int = 30

    @property
    def location(self) -> str:
        return ", ".join(part for part in [self.locality.strip(), self.city.strip()] if part)

    @property
    def query(self) -> str:
        term = " ".join(part for part in [self.category.strip(), self.keywords.strip()] if part)
        return f"{term} in {self.location}".strip()


def validate_search(params: SearchParams) -> list[str]:
    errors = []
    if not params.city.strip():
        errors.append("City or locality is required.")
    if len(params.city) > 120 or len(params.locality) > 120:
        errors.append("City/locality is too long.")
    if not params.category.strip() and not params.keywords.strip():
        errors.append("Enter a business category or search keywords.")
    if not (1 <= int(params.max_results) <= 200):
        errors.append("Maximum results must be between 1 and 200.")
    if params.provider not in {"demo", "openstreetmap", "serpapi"}:
        errors.append("Unknown discovery provider.")
    return errors


CATEGORY_TAGS: list[tuple[tuple[str, ...], list[tuple[str, str]]]] = [
    (("photograph", "photo studio", "photography"), [("shop", "photographer"), ("craft", "photographer")]),
    (("interior", "interior design", "decor"), [("shop", "interior_decoration"), ("office", "interior_design"), ("craft", "interior_decorator")]),
    (("architect",), [("office", "architect")]),
    (("event", "event planner"), [("office", "event_management"), ("shop", "event_planning")]),
    (("wedding",), [("shop", "wedding"), ("office", "wedding_planner")]),
    (("coaching", "coaching centre", "tuition", "training"), [("amenity", "training"), ("office", "educational_institution")]),
    (("salon", "spa", "beauty", "makeup", "hair"), [("shop", "beauty"), ("shop", "hairdresser"), ("leisure", "spa"), ("shop", "massage")]),
    (("restaurant", "food"), [("amenity", "restaurant")]),
    (("cafe", "coffee", "bakery"), [("amenity", "cafe"), ("shop", "bakery"), ("shop", "coffee")]),
    (("clinic", "doctor", "dental", "dentist", "health"), [("amenity", "clinic"), ("amenity", "doctors"), ("amenity", "dentist"), ("healthcare", "clinic")]),
    (("consult", "agency", "advertis", "marketing"), [("office", "consulting"), ("office", "advertising_agency")]),
    (("clothing", "clothes", "boutique", "fashion"), [("shop", "clothes"), ("shop", "boutique")]),
    (("jewel", "jewellery", "jewelry"), [("shop", "jewelry")]),
]

FALLBACK_WORDS = {"and", "in", "the", "for", "studio", "studios", "shop", "services", "service"}


def _tags_for_category(category: str) -> list[tuple[str, str]]:
    lowered = category.lower()
    for names, tags in CATEGORY_TAGS:
        if any(name in lowered for name in names):
            return tags
    return []


def _name_pattern(category: str) -> str:
    words = [
        re.escape(w) for w in re.findall(r"[A-Za-z][A-Za-z\-]+", category)
        if w.lower() not in FALLBACK_WORDS and len(w) >= 4
    ]
    if not words:
        words = [re.escape(category.strip())] if category.strip() else []
    return "|".join(words)


class BaseProvider:
    name = "base"

    def search(self, params: SearchParams, progress: ProgressFn | None = None) -> list[Business]:
        raise NotImplementedError


class DemoProvider(BaseProvider):
    name = "demo"

    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, params: SearchParams, progress: ProgressFn | None = None) -> list[Business]:
        from .demo_data import load_sample_businesses

        if progress:
            progress("Loading fictional demo records (no live scraping)")
        businesses = load_sample_businesses(self.settings.demo_csv)
        if not businesses:
            raise DiscoveryError(
                f"Demo data file not found or empty: {self.settings.demo_csv}"
            )
        return businesses[: params.max_results]


class OverpassProvider(BaseProvider):
    name = "openstreetmap"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._geo_cache: dict[str, tuple[float, float, float, float]] = {}

    def _geocode(self, location: str) -> tuple[float, float, float, float]:
        if location in self._geo_cache:
            return self._geo_cache[location]
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 0}
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": self.settings.user_agent, "Accept": "application/json"},
                timeout=self.settings.request_timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise DiscoveryError(
                "Could not reach the OpenStreetMap geocoder. Check your connection or use Demo mode."
            ) from exc
        if not data:
            raise DiscoveryError(f"Location not found: {location}. Try a more specific city or locality.")
        south, north, west, east = (float(v) for v in data[0]["boundingbox"])
        self._geo_cache[location] = (south, north, west, east)
        return (south, north, west, east)

    def _build_query(self, category: str, bbox: tuple[float, float, float, float], limit: int) -> str:
        south, north, west, east = bbox
        box = f"{south},{west},{north},{east}"
        clauses = []
        for key, value in _tags_for_category(category):
            clauses.append(f'nwr["{key}"="{value}"]({box});')
        pattern = _name_pattern(category)
        if pattern:
            clauses.append(f'nwr["name"~"{pattern}",i]({box});')
        if not clauses:
            raise DiscoveryError("Enter a category or keyword so the OpenStreetMap search can query it.")
        return f"[out:json][timeout:40];({''.join(clauses)});out center {int(limit)};"

    def _fetch_overpass(self, query: str) -> dict[str, Any]:
        endpoints = [self.settings.overpass_url]
        last_error = ""
        seen = set()
        for endpoint in endpoints:
            if endpoint in seen:
                continue
            seen.add(endpoint)
            try:
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": self.settings.user_agent},
                    timeout=max(60, self.settings.request_timeout * 3),
                )
                if response.status_code == 429:
                    last_error = "Overpass rate limit reached"
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = type(exc).__name__
                log.warning("Overpass endpoint failed: %s (%s)", endpoint, last_error)
                continue
        raise DiscoveryError(
            "OpenStreetMap/Overpass is unavailable or rate-limited right now. "
            "Try again shortly, use SerpAPI, or use Demo mode."
        )

    def search(self, params: SearchParams, progress: ProgressFn | None = None) -> list[Business]:
        if progress:
            progress(f"Locating {params.location} with OpenStreetMap Nominatim")
        bbox = self._geocode(params.location)
        time.sleep(max(0.25, min(self.settings.request_delay, 1.0)))
        query = self._build_query(params.category or params.keywords, bbox, params.max_results)
        if progress:
            progress(f"Querying public OpenStreetMap data for {params.category or params.keywords}")
        try:
            payload = self._fetch_overpass(query)
        except DiscoveryError:
            if progress:
                progress("Overpass is unavailable; trying the OpenStreetMap Nominatim fallback")
            fallback = self._nominatim_search(params)
            if fallback:
                return fallback
            raise
        elements = payload.get("elements", [])
        if not elements:
            fallback = self._nominatim_search(params)
            if fallback:
                return fallback
        results: list[Business] = []
        for element in elements:
            business = self._to_business(element, params)
            if business is not None:
                results.append(business)
            if len(results) >= params.max_results:
                break
        return results

    def _nominatim_search(self, params: SearchParams) -> list[Business]:
        """Partial fallback when Overpass is unavailable; uses the public geocoder."""
        location = params.location
        term = params.category or params.keywords
        queries = [f"{term} in {location}".strip()]
        words = [
            word for word in re.findall(r"[A-Za-z][A-Za-z\-]+", term)
            if len(word) >= 4 and word.lower() not in FALLBACK_WORDS
        ]
        for word in list(dict.fromkeys(words))[:2]:
            candidate = f"{word} in {location}".strip()
            if candidate.lower() not in {query.lower() for query in queries}:
                queries.append(candidate)

        results: list[Business] = []
        seen_listings: set[str] = set()
        for index, query in enumerate(queries):
            if index:
                time.sleep(1.1)
            payload = self._nominatim_request(query, params)
            for item in payload[: params.max_results]:
                tags = item.get("extratags") or {}
                address = item.get("address") or {}
                name = clean_text(item.get("name") or (item.get("display_name") or "").split(",")[0])
                if not name:
                    continue
                osm_type = item.get("osm_type") or "node"
                osm_id = item.get("osm_id")
                listing = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else ""
                if listing in seen_listings:
                    continue
                website = normalize_website(
                    tags.get("website") or tags.get("contact:website") or tags.get("url")
                )
                socials: list[SocialProfile] = []
                for platform in ("instagram", "facebook", "linkedin"):
                    raw = tags.get(f"contact:{platform}") or tags.get(platform)
                    if raw:
                        from .social import normalize_social_url

                        normalized = normalize_social_url(raw, platform)
                        if normalized:
                            socials.append(
                                SocialProfile(
                                    platform=platform,
                                    url=normalized,
                                    confidence=0.8,
                                    source="openstreetmap_nominatim",
                                )
                            )
                if website and any(platform in website for platform in ("instagram.com", "facebook.com", "linkedin.com")):
                    website = ""
                phone = clean_text(tags.get("phone") or tags.get("contact:phone") or tags.get("mobile"))
                email = clean_text(tags.get("email") or tags.get("contact:email")).lower()
                locality = clean_text(
                    address.get("suburb") or address.get("neighbourhood") or address.get("quarter")
                )
                city = clean_text(
                    address.get("city") or address.get("town") or address.get("village")
                ) or params.city
                if listing:
                    seen_listings.add(listing)
                results.append(
                    Business(
                        name=name,
                        category=clean_text(str(item.get("type") or params.category)).replace("_", " ").title(),
                        address=clean_text(item.get("display_name")),
                        city=city,
                        locality=locality,
                        phone=phone,
                        email=email,
                        website=website,
                        listing_url=listing,
                        rating=None,
                        review_count=None,
                        opening_hours=clean_text(tags.get("opening_hours")),
                        source="openstreetmap_nominatim",
                        collected_at=now_iso(),
                        search_query=params.query,
                        website_status="Unknown",
                        website_source="openstreetmap" if website else "",
                        phone_source="openstreetmap" if phone else "",
                        email_source="openstreetmap" if email else "",
                        socials=socials,
                    ).finalize()
                )
                if len(results) >= params.max_results:
                    return results
        return results

    def _nominatim_request(self, query: str, params: SearchParams) -> list[dict[str, Any]]:
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": min(params.max_results, 40),
                    "addressdetails": 1,
                    "extratags": 1,
                    "dedupe": 1,
                    "accept-language": "en",
                },
                headers={"User-Agent": self.settings.user_agent, "Accept": "application/json"},
                timeout=max(30, self.settings.request_timeout * 2),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Nominatim fallback failed: %s", type(exc).__name__)
            return []
        return payload if isinstance(payload, list) else []

    def _to_business(self, element: dict[str, Any], params: SearchParams) -> Business | None:
        tags = element.get("tags") or {}
        name = clean_text(tags.get("name") or tags.get("brand"))
        if not name:
            return None
        address_parts = [
            tags.get("addr:housenumber"), tags.get("addr:street"),
            tags.get("addr:suburb"), tags.get("addr:city"), tags.get("addr:postcode"),
        ]
        address = tags.get("addr:full") or ", ".join(clean_text(p) for p in address_parts if p)
        city = clean_text(tags.get("addr:city")) or params.city
        locality = clean_text(tags.get("addr:suburb") or tags.get("addr:neighbourhood")) or params.locality
        website = normalize_website(
            tags.get("website") or tags.get("contact:website") or tags.get("url")
        )
        socials: list[SocialProfile] = []
        social_tags = {
            "instagram": tags.get("contact:instagram"),
            "facebook": tags.get("contact:facebook"),
            "linkedin": tags.get("contact:linkedin"),
        }
        for platform, url in social_tags.items():
            if url:
                from .social import normalize_social_url

                normalized = normalize_social_url(url, platform)
                if normalized:
                    socials.append(
                        SocialProfile(
                            platform=platform,
                            url=normalized,
                            confidence=0.8,
                            source="openstreetmap",
                        )
                    )
        if website and any(platform in website for platform in ("instagram.com", "facebook.com", "linkedin.com")):
            website = ""
        category = (
            tags.get("shop") or tags.get("amenity") or tags.get("office")
            or tags.get("craft") or tags.get("healthcare") or params.category
        )
        element_type = element.get("type", "node")
        element_id = element.get("id")
        listing = f"https://www.openstreetmap.org/{element_type}/{element_id}" if element_id else ""
        phone = clean_text(
            tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
        )
        email = clean_text(tags.get("email") or tags.get("contact:email")).lower()
        business = Business(
            name=name,
            category=clean_text(str(category)).replace("_", " ").title(),
            address=address,
            city=city,
            locality=locality,
            phone=phone,
            email=email,
            website=website,
            listing_url=listing,
            rating=None,
            review_count=None,
            opening_hours=clean_text(tags.get("opening_hours")),
            source="openstreetmap",
            collected_at=now_iso(),
            search_query=params.query,
            website_status="Unknown",
            website_source="openstreetmap" if website else "",
            phone_source="openstreetmap" if phone else "",
            email_source="openstreetmap" if email else "",
            socials=socials,
        )
        return business.finalize()


class SerpApiProvider(BaseProvider):
    name = "serpapi"
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, params: SearchParams, progress: ProgressFn | None = None) -> list[Business]:
        if not self.settings.serpapi_key:
            raise DiscoveryError(
                "SERPAPI_KEY is not configured. Add it to .env, or use the free OpenStreetMap provider."
            )
        results: list[Business] = []
        start = 0
        while len(results) < params.max_results:
            if progress:
                progress(f"SerpAPI Google Maps page (start={start})")
            payload = self._request(params, start)
            local = payload.get("local_results") or []
            single = payload.get("place_results")
            if isinstance(single, dict):
                local = [single] + local
            if not local:
                break
            for item in local:
                business = self._to_business(item, params)
                if business is not None:
                    results.append(business)
                if len(results) >= params.max_results:
                    break
            if len(local) < 20:
                break
            start += 20
            time.sleep(self.settings.request_delay)
        return results

    def _request(self, params: SearchParams, start: int) -> dict[str, Any]:
        query = {
            "engine": "google_maps",
            "q": params.query,
            "type": "search",
            "hl": "en",
            "gl": "in",
            "start": start,
            "api_key": self.settings.serpapi_key,
        }
        try:
            response = requests.get(
                self.endpoint,
                params=query,
                timeout=max(20, self.settings.request_timeout),
            )
        except requests.RequestException as exc:
            raise DiscoveryError(
                "SerpAPI request failed. Check your internet connection and API key."
            ) from exc
        if response.status_code in {401, 403}:
            raise DiscoveryError("SerpAPI rejected the API key (HTTP 401/403). Check SERPAPI_KEY.")
        if response.status_code == 429:
            raise DiscoveryError("SerpAPI quota/rate limit reached (HTTP 429).")
        if response.status_code >= 400:
            raise DiscoveryError(f"SerpAPI returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DiscoveryError("SerpAPI returned an invalid response.") from exc
        if payload.get("error"):
            message = str(payload["error"])
            if self.settings.serpapi_key:
                message = message.replace(self.settings.serpapi_key, "[redacted]")
            raise DiscoveryError(f"SerpAPI error: {message}")
        return payload

    def _to_business(self, item: dict[str, Any], params: SearchParams) -> Business | None:
        name = clean_text(item.get("title"))
        if not name:
            return None
        links = item.get("links") or {}
        place_id = item.get("place_id") or ""
        listing = links.get("place") or (
            f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ""
        )
        hours = item.get("hours")
        if isinstance(hours, list):
            hours_text = "; ".join(
                f"{h.get('day', '')}: {h.get('hours', '')}" for h in hours if isinstance(h, dict)
            )
        else:
            hours_text = clean_text(item.get("operating_hours"))
        address = clean_text(item.get("address"))
        city = params.city
        locality = params.locality
        address_parts = [p.strip() for p in address.split(",") if p.strip()]
        if address_parts and not locality and len(address_parts) >= 2:
            locality = address_parts[-2]
        business = Business(
            name=name,
            category=clean_text(item.get("type") or item.get("types") or params.category),
            address=address,
            city=city,
            locality=locality,
            phone=clean_text(item.get("phone")),
            email="",
            website=normalize_website(item.get("website") or links.get("website")),
            listing_url=listing,
            rating=parse_float(item.get("rating")),
            review_count=parse_int(item.get("reviews")),
            opening_hours=hours_text,
            source="serpapi",
            collected_at=now_iso(),
            search_query=params.query,
            website_status="Unknown",
            website_source="serpapi" if (item.get("website") or links.get("website")) else "",
            phone_source="serpapi" if item.get("phone") else "",
        )
        return business.finalize()


def get_provider(settings: Settings, provider: str) -> BaseProvider:
    if provider == "demo":
        return DemoProvider(settings)
    if provider == "serpapi":
        return SerpApiProvider(settings)
    if provider == "openstreetmap":
        return OverpassProvider(settings)
    raise DiscoveryError(f"Unknown provider: {provider}")
