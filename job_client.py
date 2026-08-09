"""
Clients for the three job-posting sources, each normalized to one document
schema matching the ``job_postings`` table.

    Adzuna    -- https://developer.adzuna.com/           (app_id + app_key)
    USAJobs   -- https://developer.usajobs.gov/           (API key + email)
    RemoteOK  -- https://remoteok.com/api                 (no key)

Every normalized document has the same shape regardless of source, which is
what lets one harvest endpoint and (in Phase 2) one embedding pipeline serve
all three:

    id, source, external_id, title, company, location, remote,
    salary_min, salary_max, salary_currency, employment_type, category,
    description_text, apply_url, posted_at, content_hash, payload
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 20

SOURCE_ADZUNA = "adzuna"
SOURCE_USAJOBS = "usajobs"
SOURCE_REMOTEOK = "remoteok"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def content_hash(text: str) -> str:
    """Stable hash of a narrative, used to detect changed postings on re-sync."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_iso(value: str | None) -> str | None:
    """Normalize an ISO-8601 timestamp to UTC, or return None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _looks_remote(*texts: str | None) -> bool:
    combined = " ".join(t for t in texts if t).lower()
    return "remote" in combined


# ---------------------------------------------------------------------------
# Adzuna
# ---------------------------------------------------------------------------


class AdzunaClient:
    """https://developer.adzuna.com/docs/search

    Auth is two query parameters (app_id, app_key) on every request -- no
    headers involved. Country is a path segment (us, gb, de, ...).
    """

    BASE_URL = "https://api.adzuna.com/v1/api"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        country: str = "us",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.timeout = timeout
        self._session = requests.Session()

    def search(
        self,
        what: str,
        where: str = "",
        page: int = 1,
        results_per_page: int = 25,
        max_days_old: int | None = None,
        salary_min: float | None = None,
        full_time: bool | None = None,
    ) -> list[dict]:
        """Raw Adzuna result objects for one query."""
        params: dict[str, Any] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": results_per_page,
            "what": what,
            "content-type": "application/json",
        }
        if where:
            params["where"] = where
        if max_days_old is not None:
            params["max_days_old"] = max_days_old
        if salary_min is not None:
            params["salary_min"] = salary_min
        if full_time:
            params["full_time"] = 1

        url = f"{self.BASE_URL}/jobs/{self.country}/search/{page}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("results", []) or []

    @staticmethod
    def normalize(raw: dict) -> dict | None:
        external_id = raw.get("id")
        title = raw.get("title")
        description = _clean_whitespace(raw.get("description") or "")
        if not external_id or not title or not description:
            return None

        location = (raw.get("location") or {}).get("display_name")
        company = (raw.get("company") or {}).get("display_name")
        category = (raw.get("category") or {}).get("label")

        employment_type = raw.get("contract_time") or raw.get("contract_type")

        return {
            "id": f"{SOURCE_ADZUNA}:{external_id}",
            "source": SOURCE_ADZUNA,
            "external_id": str(external_id),
            "title": title,
            "company": company,
            "location": location,
            "remote": _looks_remote(location, title),
            "salary_min": raw.get("salary_min"),
            "salary_max": raw.get("salary_max"),
            "salary_currency": "USD",
            "employment_type": employment_type,
            "category": category,
            "description_text": description,
            "apply_url": raw.get("redirect_url"),
            "posted_at": _parse_iso(raw.get("created")),
            "content_hash": content_hash(description),
            "payload": raw,
        }


# ---------------------------------------------------------------------------
# USAJobs
# ---------------------------------------------------------------------------


class USAJobsClient:
    """https://developer.usajobs.gov/api-reference/get-api-search

    Auth is three request headers, not query parameters: Host (always
    'data.usajobs.gov'), User-Agent (the email registered for the key), and
    Authorization-Key (the API key itself).
    """

    URL = "https://data.usajobs.gov/api/Search"

    def __init__(self, api_key: str, email: str, timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key
        self.email = email
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Host": "data.usajobs.gov",
                "User-Agent": email,
                "Authorization-Key": api_key,
            }
        )

    def search(
        self,
        keyword: str,
        location: str | None = None,
        results_per_page: int = 100,
        page: int = 1,
        remote: bool | None = None,
    ) -> list[dict]:
        """Raw USAJobs SearchResultItems for one query."""
        params: dict[str, Any] = {
            "Keyword": keyword,
            "ResultsPerPage": min(results_per_page, 500),
            "Page": page,
            "Fields": "full",
        }
        if location:
            params["LocationName"] = location
        if remote is not None:
            params["RemoteIndicator"] = "true" if remote else "false"

        resp = self._session.get(self.URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return (
            data.get("SearchResult", {}).get("SearchResultItems", []) or []
        )

    @staticmethod
    def normalize(raw: dict) -> dict | None:
        external_id = raw.get("MatchedObjectId")
        descriptor = raw.get("MatchedObjectDescriptor") or {}
        title = descriptor.get("PositionTitle")
        if not external_id or not title:
            return None

        details = (descriptor.get("UserArea") or {}).get("Details") or {}
        summary_parts = [
            descriptor.get("QualificationSummary") or "",
            details.get("JobSummary") or "",
            details.get("MajorDuties") or "",
        ]
        description = _clean_whitespace(" ".join(p for p in summary_parts if p))
        if not description:
            return None

        remuneration = (descriptor.get("PositionRemuneration") or [{}])[0]

        def _to_number(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        schedule = (descriptor.get("PositionSchedule") or [{}])[0]
        job_category = (descriptor.get("JobCategory") or [{}])[0]

        apply_uris = descriptor.get("ApplyURI") or []
        apply_url = apply_uris[0] if apply_uris else descriptor.get("PositionURI")

        location = descriptor.get("PositionLocationDisplay")

        return {
            "id": f"{SOURCE_USAJOBS}:{external_id}",
            "source": SOURCE_USAJOBS,
            "external_id": str(external_id),
            "title": title,
            "company": descriptor.get("OrganizationName") or descriptor.get("DepartmentName"),
            "location": location,
            "remote": _looks_remote(location, title),
            "salary_min": _to_number(remuneration.get("MinimumRange")),
            "salary_max": _to_number(remuneration.get("MaximumRange")),
            "salary_currency": "USD",
            "employment_type": schedule.get("Name"),
            "category": job_category.get("Name"),
            "description_text": description,
            "apply_url": apply_url,
            "posted_at": _parse_iso(descriptor.get("PublicationStartDate")),
            "content_hash": content_hash(description),
            "payload": raw,
        }


# ---------------------------------------------------------------------------
# RemoteOK
# ---------------------------------------------------------------------------

# RemoteOK's anti-scraper honeypot line ("Please mention the word X and tag
# Y...") is appended to every real description. It is boilerplate, not
# content -- stripped so it doesn't pollute what gets embedded in Phase 2 or
# shown to a user.
_REMOTEOK_HONEYPOT_RE = re.compile(
    r"please mention the word.*?(?:$)", re.IGNORECASE | re.DOTALL
)

# RemoteOK's public feed is noisy: test posts, dead/placeholder listings,
# and non-job spam show up mixed in with real postings. This is a cheap
# hygiene filter, not scam detection -- that's a deliberately separate,
# LLM-backed tool added later. This just drops the obviously-empty cases so
# they don't clutter search results at all.
_MIN_DESCRIPTION_WORDS = 12


class RemoteOKClient:
    """https://remoteok.com/api -- no API key required.

    RemoteOK's terms ask API consumers to link back to remoteok.com and
    credit it as the source; both are honored in the normalized document
    (``apply_url`` and ``source``) and should stay visible anywhere listings
    from this source are displayed in the UI.
    """

    URL = "https://remoteok.com/api"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, contact: str = ""):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": f"job-hunting-copilot/1.0 (contact: {contact or 'not set'})",
                "Accept": "application/json",
            }
        )

    def fetch_all(self) -> list[dict]:
        """Raw RemoteOK listings. The first array element is a legal notice,
        not a job -- it has no 'id' field and is skipped here."""
        resp = self._session.get(self.URL, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return [item for item in data if isinstance(item, dict) and item.get("id")]

    @staticmethod
    def normalize(raw: dict) -> dict | None:
        external_id = raw.get("id")
        title = raw.get("position")
        if not external_id or not title:
            return None

        description = _strip_html(raw.get("description") or "")
        description = _REMOTEOK_HONEYPOT_RE.sub("", description)
        description = _clean_whitespace(description)
        if len(description.split()) < _MIN_DESCRIPTION_WORDS:
            return None

        posted_at = None
        epoch = raw.get("epoch")
        if isinstance(epoch, (int, float)) and epoch > 0:
            posted_at = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        else:
            posted_at = _parse_iso(raw.get("date"))

        salary_min = raw.get("salary_min") or None
        salary_max = raw.get("salary_max") or None

        tags = raw.get("tags") or []
        category = tags[0] if tags else None

        return {
            "id": f"{SOURCE_REMOTEOK}:{external_id}",
            "source": SOURCE_REMOTEOK,
            "external_id": str(external_id),
            "title": title,
            "company": raw.get("company"),
            "location": raw.get("location") or "Remote",
            "remote": True,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": "USD",
            "employment_type": None,
            "category": category,
            "description_text": description,
            "apply_url": raw.get("apply_url") or raw.get("url"),
            "posted_at": posted_at,
            "content_hash": content_hash(description),
            "payload": raw,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class JobSearchClient:
    """Fetches and normalizes postings across whichever sources are configured.

    Any of the three underlying clients may be ``None`` (e.g. no USAJobs key
    yet) -- that source is simply skipped rather than raising.
    """

    def __init__(
        self,
        adzuna: AdzunaClient | None = None,
        usajobs: USAJobsClient | None = None,
        remoteok: RemoteOKClient | None = None,
    ):
        self.adzuna = adzuna
        self.usajobs = usajobs
        self.remoteok = remoteok

    def fetch_all(
        self,
        queries: Iterable[dict],
        limit_per_source: int = 50,
    ) -> tuple[list[dict], list[dict]]:
        """Harvest normalized postings for a list of {"keyword", "location"} queries.

        Returns ``(documents, errors)``. RemoteOK has no server-side keyword
        search, so it's fetched once and filtered client-side against every
        query's keyword; Adzuna and USAJobs are queried once per entry in
        ``queries``.
        """
        documents: list[dict] = []
        errors: list[dict] = []
        seen_ids: set[str] = set()

        def _add(doc: dict | None):
            if doc and doc["id"] not in seen_ids:
                seen_ids.add(doc["id"])
                documents.append(doc)

        queries = list(queries)

        for query in queries:
            keyword = query.get("keyword", "")
            location = query.get("location", "")

            if self.adzuna:
                try:
                    for raw in self.adzuna.search(
                        keyword, where=location, results_per_page=limit_per_source
                    ):
                        _add(AdzunaClient.normalize(raw))
                except requests.RequestException as exc:
                    errors.append({"source": SOURCE_ADZUNA, "query": query, "error": str(exc)})

            if self.usajobs:
                try:
                    for raw in self.usajobs.search(
                        keyword, location=location, results_per_page=limit_per_source
                    ):
                        _add(USAJobsClient.normalize(raw))
                except requests.RequestException as exc:
                    errors.append({"source": SOURCE_USAJOBS, "query": query, "error": str(exc)})

        if self.remoteok:
            try:
                raw_listings = self.remoteok.fetch_all()
                keywords = [q.get("keyword", "").lower() for q in queries if q.get("keyword")]

                per_source_count = 0
                for raw in raw_listings:
                    if per_source_count >= limit_per_source * max(len(queries), 1):
                        break
                    if keywords:
                        haystack = " ".join(
                            [
                                str(raw.get("position") or ""),
                                " ".join(raw.get("tags") or []),
                            ]
                        ).lower()
                        if not any(kw in haystack for kw in keywords):
                            continue
                    doc = RemoteOKClient.normalize(raw)
                    if doc:
                        _add(doc)
                        per_source_count += 1
            except requests.RequestException as exc:
                errors.append({"source": SOURCE_REMOTEOK, "query": None, "error": str(exc)})

        return documents, errors
