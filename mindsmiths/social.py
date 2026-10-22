"""Extract official social profile links from a business's own website."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import SocialProfile, slug

PLATFORM_HOSTS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "linkedin.com": "linkedin",
}

SKIP_PATHS = {
    "instagram": {"", "explore", "reel", "reels", "p", "stories", "accounts", "about",
                  "legal", "developer", "directory", "share", "tv", "topics", "popular",
                  "reelsaudio", "guides"},
    "facebook": {"", "sharer", "sharer.php", "dialog", "login", "login.php", "plugins",
                 "help", "policies", "privacy", "groups", "events", "watch", "marketplace",
                 "share", "share.php", "profile.php", "photo", "photo.php", "permalink.php",
                 "story.php", "reel", "reels", "media", "p", "hashtag"},
    "linkedin": {"", "sharearticle", "sharing", "login", "feed", "jobs", "help", "legal",
                 "pulse", "posts", "learning"},
}

GENERIC_HANDLES = {"business", "official", "shop", "store", "company", "contact", "home"}


def _host_platform(host: str) -> tuple[str, str] | None:
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    for domain, platform in PLATFORM_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return platform, host
    return None


def normalize_social_url(url: str, platform: str) -> str:
    parsed = urlparse(url if url.startswith("http") else "https://" + url)
    parts = [p for p in parsed.path.split("/") if p]
    if platform == "instagram":
        if not parts:
            return ""
        return f"https://www.instagram.com/{parts[0]}/"
    if platform == "facebook":
        if not parts:
            return ""
        if parts[0] == "pages" and len(parts) >= 3:
            return f"https://www.facebook.com/{parts[2]}/"
        if parts[0] == "profile.php":
            return f"https://www.facebook.com/profile.php?id={parts[0]}"
        return f"https://www.facebook.com/{parts[0]}/"
    if platform == "linkedin":
        if len(parts) < 2 or parts[0] not in {"company", "in", "school"}:
            return ""
        return f"https://www.linkedin.com/{parts[0]}/{parts[1]}/"
    return ""


def _confidence(url: str, business_name: str, source: str = "website") -> float:
    handle = slug(urlparse(url).path)
    name_tokens = [slug(t) for t in re.split(r"\W+", business_name) if len(slug(t)) >= 3]
    if name_tokens and any(token in handle for token in name_tokens):
        return 0.9
    if any(generic in handle for generic in GENERIC_HANDLES):
        return 0.6
    return 0.72 if source == "website" else 0.5


def _consider(best: dict[str, SocialProfile], href: str, business_name: str, source: str) -> None:
    if not href or not href.startswith("http"):
        return
    parsed = urlparse(href)
    found = _host_platform(parsed.netloc)
    if found is None:
        return
    platform, _ = found
    path_parts = [p.lower() for p in parsed.path.split("/") if p]
    if path_parts and path_parts[0] in SKIP_PATHS[platform]:
        return
    url = normalize_social_url(href, platform)
    if not url:
        return
    candidate = SocialProfile(
        platform=platform,
        url=url,
        followers=None,
        followers_verified=False,
        activity_verified=False,
        last_active=None,
        confidence=_confidence(url, business_name, source),
        source=source,
    )
    current = best.get(platform)
    if current is None or candidate.confidence > current.confidence:
        best[platform] = candidate


def _same_as_urls(value) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        if value.startswith("http"):
            urls.append(value)
    elif isinstance(value, list):
        for item in value:
            urls.extend(_same_as_urls(item))
    elif isinstance(value, dict):
        for key in ("sameAs", "url"):
            if key in value:
                urls.extend(_same_as_urls(value[key]))
    return urls


def extract_social_links(html: str, base_url: str, business_name: str) -> list[SocialProfile]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    best: dict[str, SocialProfile] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        _consider(best, href, business_name, "website")

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for url in _same_as_urls(payload):
            _consider(best, url, business_name, "website")
    return list(best.values())


def platform_from_url(url: str) -> str:
    parsed = urlparse(url if url.startswith("http") else "https://" + url)
    found = _host_platform(parsed.netloc)
    return found[0] if found else ""
