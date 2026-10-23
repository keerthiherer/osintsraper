"""Compliant provider connectors for freelance and remote-work listings.

Only public APIs or documented public endpoints are used. No login walls,
CAPTCHAs, anti-bot bypasses or unauthorised scraping are implemented.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import Settings
from .models import FreelanceOpportunity, ProviderResult, ProviderStatus

log = logging.getLogger(__name__)

WEB_TECH = {
    "website", "web development", "web design", "landing page", "wordpress",
    "shopify", "e-commerce", "ecommerce", "react", "next.js", "nextjs", "django",
    "flask", "frontend", "front-end", "backend", "back-end", "full stack", "full-stack",
    "redesign", "website maintenance", "performance optimization", "performance optimisation",
    "seo", "webflow", "php", "javascript", "html", "css", "api development",
}


def _iso_from_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()


def _iso(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("Z", "+00:00")


def _budget_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class BaseFreelanceProvider:
    name = "base"
    label = "Base"
    docs_url = ""
    requires_key = False

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, label=self.label, state="available", detail="")

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        raise NotImplementedError

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
        })
        return session


class FreelancerProvider(BaseFreelanceProvider):
    """Freelancer.com public projects API (no key required at time of writing)."""

    name = "freelancer"
    label = "Freelancer.com"
    docs_url = "https://developers.freelancer.com/"
    requires_key = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="available",
            detail="Public active-projects API. No key needed. Respect Freelancer's terms and rate limits.",
            docs_url=self.docs_url,
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        params = {
            "query": query,
            "limit": max(1, min(int(limit), 100)),
            "job_details": "true",
            "full_description": "true",
            "sort": "time_updated",
            "owner_info": "true",
        }
        session = self._session()
        try:
            response = session.get(
                self.settings.freelancer_api_url,
                params=params,
                timeout=max(20, self.settings.request_timeout),
            )
            if response.status_code == 429:
                return ProviderResult(provider=self.name, error="Rate limited by Freelancer.com.", status="rate-limited", checked_at=checked_at)
            if response.status_code >= 400:
                return ProviderResult(provider=self.name, error=f"Freelancer.com returned HTTP {response.status_code}.", status="error", checked_at=checked_at)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return ProviderResult(provider=self.name, error=f"Freelancer.com request failed ({type(exc).__name__}).", status="error", checked_at=checked_at)
        finally:
            session.close()

        projects = ((payload or {}).get("result") or {}).get("projects") or []
        results: list[FreelanceOpportunity] = []
        for item in projects:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            status = str(item.get("status") or "").lower()
            deleted = bool(item.get("deleted"))
            project_status = (
                "Open and verified" if status == "active" and not deleted
                else "Closed or expired"
            )
            currency = ((item.get("currency") or {}).get("code") or "").strip().upper()
            budget = item.get("budget") or {}
            if not isinstance(budget, dict):
                budget = {}
            hourly = item.get("hourly_project_info") or {}
            if not isinstance(hourly, dict):
                hourly = {}
            budget_min = _budget_number(budget.get("minimum")) or _budget_number(hourly.get("hourly_min"))
            budget_max = _budget_number(budget.get("maximum")) or _budget_number(hourly.get("hourly_max"))
            jobs = item.get("jobs") or []
            skills = ", ".join(
                str(job.get("name")) for job in jobs if isinstance(job, dict) and job.get("name")
            )
            posted = _iso_from_timestamp(item.get("time_submitted") or item.get("submitdate"))
            deadline = ""
            bid_period = item.get("bidperiod")
            if posted and bid_period:
                try:
                    deadline = (
                        datetime.fromisoformat(posted.replace("Z", "+00:00"))
                        + timedelta(days=int(bid_period))
                    ).replace(microsecond=0).isoformat()
                except (ValueError, TypeError):
                    deadline = ""
            owner = item.get("owner_info") if isinstance(item.get("owner_info"), dict) else {}
            client_bits = []
            for key in ("username", "display_name", "country", "city", "company_name"):
                value = owner.get(key)
                if isinstance(value, dict):
                    value = value.get("name") or value.get("code")
                if value:
                    client_bits.append(str(value))
            location = item.get("location") if isinstance(item.get("location"), dict) else {}
            country = ((location.get("country") or {}).get("name") if isinstance(location.get("country"), dict) else None)
            if country:
                client_bits.append(str(country))
            bid_stats = item.get("bid_stats") if isinstance(item.get("bid_stats"), dict) else {}
            proposal_count = bid_stats.get("bid_count")
            seo_url = (item.get("seo_url") or "").strip()
            url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else "https://www.freelancer.com/"
            description = item.get("description") or item.get("preview_description") or ""
            if not description:
                description = item.get("preview_description") or ""
            results.append(FreelanceOpportunity(
                platform="Freelancer.com",
                external_id=str(item.get("id") or ""),
                title=str(item.get("title")),
                url=url,
                description=str(description)[:8000],
                posted_at=posted,
                deadline=deadline,
                budget_min=budget_min,
                budget_max=budget_max,
                budget_type="Hourly" if str(item.get("type")).lower() == "hourly" else "Fixed price",
                currency=currency,
                skills=skills,
                experience="Client experience requirement not disclosed" if not item.get("qualifications") else str(item.get("qualifications")),
                client_info=" · ".join(dict.fromkeys(client_bits)) or "Client details not disclosed by the platform",
                proposal_count=int(proposal_count) if proposal_count is not None else None,
                project_status=project_status,
                status_verified=True,
                last_checked_at=checked_at,
                source_query=query,
            ))
        return ProviderResult(provider=self.name, opportunities=results, checked_at=checked_at)


class RemotiveProvider(BaseFreelanceProvider):
    """Remotive public remote-jobs API. These are jobs, not freelance bids."""

    name = "remotive"
    label = "Remotive (remote jobs)"
    docs_url = "https://remotive.com/remote-jobs/api"
    requires_key = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="available",
            detail="Public remote-job API. Listings are jobs, not freelance projects; status may change on the source.",
            docs_url=self.docs_url,
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        session = self._session()
        try:
            response = session.get(
                self.settings.remotive_api_url,
                params={"search": query, "limit": max(1, min(int(limit), 100))},
                timeout=max(20, self.settings.request_timeout),
            )
            if response.status_code == 429:
                return ProviderResult(provider=self.name, error="Rate limited by Remotive.", status="rate-limited", checked_at=checked_at)
            if response.status_code >= 400:
                return ProviderResult(provider=self.name, error=f"Remotive returned HTTP {response.status_code}.", status="error", checked_at=checked_at)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return ProviderResult(provider=self.name, error=f"Remotive request failed ({type(exc).__name__}).", status="error", checked_at=checked_at)
        finally:
            session.close()

        results: list[FreelanceOpportunity] = []
        for item in (payload or {}).get("jobs", [])[:limit]:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            salary = str(item.get("salary") or "")
            results.append(FreelanceOpportunity(
                platform="Remotive (remote jobs)",
                external_id=str(item.get("id") or item.get("url") or ""),
                title=title,
                url=str(item.get("url") or ""),
                description=str(item.get("description") or "")[:8000],
                posted_at=_iso(item.get("publication_date")),
                deadline="",
                budget_min=None,
                budget_max=None,
                budget_type="Remote job",
                currency="",
                skills=", ".join(item.get("tags") or []),
                experience=str(item.get("job_type") or "Not disclosed"),
                client_info=str(item.get("company_name") or "Company not disclosed"),
                proposal_count=None,
                project_status="Possibly open; status unconfirmed",
                status_verified=False,
                last_checked_at=checked_at,
                source_query=query,
            ))
            if salary and results:
                results[-1].description = (results[-1].description + f"\n\nSalary (as listed): {salary}")[:8000]
        return ProviderResult(provider=self.name, opportunities=results, checked_at=checked_at)


class ArbeitnowProvider(BaseFreelanceProvider):
    """Arbeitnow public job board API. Search is applied locally."""

    name = "arbeitnow"
    label = "Arbeitnow (remote jobs)"
    docs_url = "https://www.arbeitnow.com/api/job-board-api"
    requires_key = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="available",
            detail="Public job-board API. Listings are jobs, not freelance projects; status may change on the source.",
            docs_url=self.docs_url,
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        session = self._session()
        try:
            response = session.get(
                self.settings.arbeitnow_api_url,
                timeout=max(20, self.settings.request_timeout),
            )
            if response.status_code >= 400:
                return ProviderResult(provider=self.name, error=f"Arbeitnow returned HTTP {response.status_code}.", status="error", checked_at=checked_at)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return ProviderResult(provider=self.name, error=f"Arbeitnow request failed ({type(exc).__name__}).", status="error", checked_at=checked_at)
        finally:
            session.close()

        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9.+#-]+", query) if len(term) > 2]
        results: list[FreelanceOpportunity] = []
        for item in (payload or {}).get("data", []):
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "")
            haystack = f"{title} {description} {' '.join(item.get('tags') or [])}".lower()
            if terms and not any(term in haystack for term in terms):
                continue
            if title:
                results.append(FreelanceOpportunity(
                    platform="Arbeitnow (remote jobs)",
                    external_id=str(item.get("slug") or item.get("url") or ""),
                    title=title,
                    url=str(item.get("url") or ""),
                    description=description[:8000],
                    posted_at=_iso_from_timestamp(item.get("created_at")),
                    deadline="",
                    budget_min=None,
                    budget_max=None,
                    budget_type="Remote job",
                    currency="",
                    skills=", ".join(item.get("tags") or []),
                    experience=str(item.get("job_types") or "Not disclosed"),
                    client_info=str(item.get("company_name") or "Company not disclosed"),
                    proposal_count=None,
                    project_status="Possibly open; status unconfirmed",
                    status_verified=False,
                    last_checked_at=checked_at,
                    source_query=query,
                ))
            if len(results) >= limit:
                break
        return ProviderResult(provider=self.name, opportunities=results, checked_at=checked_at)


class UpworkProvider(BaseFreelanceProvider):
    """Upwork's GraphQL API requires an OAuth access token."""

    name = "upwork"
    label = "Upwork (API token required)"
    docs_url = "https://developers.upwork.com/"
    requires_key = True

    def status(self) -> ProviderStatus:
        if self.settings.upwork_access_token:
            return ProviderStatus(
                name=self.name,
                label=self.label,
                state="configured",
                detail="UPWORK_ACCESS_TOKEN is set. The connector is experimental; verify the current API schema.",
                docs_url=self.docs_url,
                requires_key=True,
            )
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="configuration-required",
            detail="Set UPWORK_ACCESS_TOKEN. Upwork does not permit unauthenticated marketplace scraping.",
            docs_url=self.docs_url,
            requires_key=True,
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if not self.settings.upwork_access_token:
            return ProviderResult(
                provider=self.name,
                error="Upwork requires an OAuth access token; this provider is disabled until configured.",
                status="configuration-required",
                checked_at=checked_at,
            )
        graphql = """
        query SearchJobs($query: String!, $limit: Int!) {
          marketplaceJobPostingsSearch(
            marketPlaceJobFilter: {searchTerm: $query}
            searchType: USER_JOBS_SEARCH
            sortAttributes: [{field: RECENCY}]
            limit: $limit
          ) {
            edges {
              node {
                id title description ciphertext
                createdDateTime
                amount { rawValue currency }
                hourlyBudgetMin { rawValue currency }
                hourlyBudgetMax { rawValue currency }
                skills { name }
                client { companyName country }
                proposalsTier
              }
            }
          }
        }
        """
        session = self._session()
        try:
            response = session.post(
                self.settings.upwork_graphql_url,
                json={"query": graphql, "variables": {"query": query, "limit": max(1, min(limit, 50))}},
                headers={"Authorization": f"Bearer {self.settings.upwork_access_token}"},
                timeout=max(20, self.settings.request_timeout),
            )
            if response.status_code in {401, 403}:
                return ProviderResult(provider=self.name, error="Upwork rejected the access token.", status="error", checked_at=checked_at)
            if response.status_code >= 400:
                return ProviderResult(provider=self.name, error=f"Upwork returned HTTP {response.status_code}.", status="error", checked_at=checked_at)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return ProviderResult(provider=self.name, error=f"Upwork request failed ({type(exc).__name__}).", status="error", checked_at=checked_at)
        finally:
            session.close()

        if payload.get("errors"):
            message = str(payload["errors"][0].get("message") if isinstance(payload["errors"][0], dict) else payload["errors"][0])
            message = message.replace(self.settings.upwork_access_token, "[redacted]")
            return ProviderResult(provider=self.name, error=f"Upwork API error: {message}", status="error", checked_at=checked_at)
        edges = (((payload.get("data") or {}).get("marketplaceJobPostingsSearch") or {}).get("edges")) or []
        results: list[FreelanceOpportunity] = []
        for edge in edges:
            node = edge.get("node") or {}
            title = str(node.get("title") or "").strip()
            if not title:
                continue
            amount = node.get("amount") or {}
            hourly_min = node.get("hourlyBudgetMin") or {}
            hourly_max = node.get("hourlyBudgetMax") or {}
            budget = amount or hourly_min or hourly_max
            currency = str(budget.get("currency") or "")
            results.append(FreelanceOpportunity(
                platform="Upwork",
                external_id=str(node.get("id") or ""),
                title=title,
                url=f"https://www.upwork.com/jobs/{node.get('ciphertext')}" if node.get("ciphertext") else "https://www.upwork.com/",
                description=str(node.get("description") or "")[:8000],
                posted_at=_iso(node.get("createdDateTime")),
                budget_min=_budget_number(hourly_min.get("rawValue") or amount.get("rawValue")),
                budget_max=_budget_number(hourly_max.get("rawValue") or amount.get("rawValue")),
                budget_type="Hourly" if hourly_min or hourly_max else "Fixed price",
                currency=currency,
                skills=", ".join(
                    str(skill.get("name")) for skill in (node.get("skills") or []) if isinstance(skill, dict)
                ),
                experience="Not disclosed",
                client_info=str((node.get("client") or {}).get("companyName") or (node.get("client") or {}).get("country") or "Client details not disclosed"),
                proposal_count=None,
                project_status="Open and verified",
                status_verified=True,
                last_checked_at=checked_at,
                source_query=query,
            ))
        return ProviderResult(provider=self.name, opportunities=results, checked_at=checked_at)


class UnavailableProvider(BaseFreelanceProvider):
    def __init__(self, settings: Settings, name: str, label: str, detail: str, docs_url: str = ""):
        super().__init__(settings)
        self.name = name
        self.label = label
        self._detail = detail
        self.docs_url = docs_url

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="unavailable",
            detail=self._detail,
            docs_url=self.docs_url,
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            error=self._detail,
            status="unavailable",
            checked_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )


class DemoFreelanceProvider(BaseFreelanceProvider):
    name = "demo"
    label = "Demo listings (fictional, testing only)"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            state="available",
            detail="Fictional sample listings for UI testing. Never presented as live opportunities.",
        )

    def search(self, query: str, limit: int = 50) -> ProviderResult:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        samples = [
            FreelanceOpportunity(
                platform="Demo (fictional)",
                external_id="demo-1",
                title="WordPress business website refresh (sample)",
                url="https://example.invalid/demo/wordpress-refresh",
                description="Fictional sample listing used to test the interface. Not a real client or project.",
                posted_at=today,
                deadline="",
                budget_min=25000,
                budget_max=40000,
                budget_type="Fixed price",
                currency="INR",
                skills="WordPress, Web Design, SEO",
                experience="Not disclosed",
                client_info="Fictional sample client",
                proposal_count=4,
                project_status="Demo sample (fictional)",
                status_verified=False,
                last_checked_at=checked_at,
                source_query=query,
                is_demo=True,
            ),
            FreelanceOpportunity(
                platform="Demo (fictional)",
                external_id="demo-2",
                title="Next.js landing page for a local service business (sample)",
                url="https://example.invalid/demo/nextjs-landing",
                description="Fictional sample listing. It exists only to test scoring and filters.",
                posted_at=today,
                deadline="",
                budget_min=12000,
                budget_max=20000,
                budget_type="Fixed price",
                currency="INR",
                skills="React, Next.js, Landing Page",
                experience="Not disclosed",
                client_info="Fictional sample client",
                proposal_count=9,
                project_status="Demo sample (fictional)",
                status_verified=False,
                last_checked_at=checked_at,
                source_query=query,
                is_demo=True,
            ),
        ]
        matches = []
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9.+#-]+", query)]
        for item in samples:
            haystack = f"{item.title} {item.description} {item.skills}".lower()
            if not terms or any(term in haystack for term in terms):
                matches.append(item)
        return ProviderResult(provider=self.name, opportunities=matches[:limit], checked_at=checked_at)


def all_providers(settings: Settings) -> dict[str, BaseFreelanceProvider]:
    providers: list[BaseFreelanceProvider] = [
        FreelancerProvider(settings),
        RemotiveProvider(settings),
        ArbeitnowProvider(settings),
        UpworkProvider(settings),
        DemoFreelanceProvider(settings),
        UnavailableProvider(
            settings, "peopleperhour", "PeoplePerHour",
            "No documented public API is available. Use the platform manually; this tool does not scrape it.",
            "https://www.peopleperhour.com/",
        ),
        UnavailableProvider(
            settings, "guru", "Guru",
            "No documented public API is available. Use the platform manually; this tool does not scrape it.",
            "https://www.guru.com/",
        ),
    ]
    return {provider.name: provider for provider in providers}
