# Endpoint: https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
# Public, unauthenticated POST search API used by Workday's own career-site
# frontend. tenant/dc/site vary per company and aren't derivable from the
# company name alone -- find them by visiting the company's public careers
# page and reading the URL, e.g. https://salesforce.wd12.myworkdayjobs.com/External_Career_Site
# -> tenant=salesforce, dc=wd12, site=External_Career_Site.
# Verified live (2026-07) against Salesforce: total/jobPostings/externalPath/
# locationsText/postedOn fields all present and stable.
import re
from datetime import datetime, timedelta, timezone

import requests

from .base import HEADERS, Job

PAGE_SIZE = 20
MAX_RESULTS = 200  # safety cap across pagination for very broad queries

_REQ_ID_RE = re.compile(r"_([A-Za-z0-9-]+)$")
_DAYS_AGO_RE = re.compile(r"(\d+)\+?\s*day", re.IGNORECASE)


def _job_id(tenant: str, external_path: str) -> str:
    m = _REQ_ID_RE.search(external_path)
    suffix = m.group(1) if m else external_path
    return f"workday_{tenant}_{suffix}"


def _normalize_posted_on(posted_on: str | None) -> str | None:
    # postedOn is a relative human string ("Posted Today", "Posted 3 Days
    # Ago", "Posted 30+ Days Ago"), not an absolute date -- approximate it
    # as an ISO timestamp so filters.py can parse it uniformly.
    if not posted_on:
        return None
    text = posted_on.lower()
    now = datetime.now(timezone.utc)
    if "today" in text:
        return now.isoformat()
    if "yesterday" in text:
        return (now - timedelta(days=1)).isoformat()
    m = _DAYS_AGO_RE.search(text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).isoformat()
    return None


def normalize(raw: dict, tenant: str, dc: str, site: str, company_name: str) -> Job:
    external_path = raw["externalPath"]
    return Job(
        job_id=_job_id(tenant, external_path),
        title=raw["title"],
        company=company_name,
        url=f"https://{tenant}.{dc}.myworkdayjobs.com/{site}{external_path}",
        location=raw.get("locationsText"),
        posted_date=_normalize_posted_on(raw.get("postedOn")),
    )


def fetch(params: dict) -> list[Job]:
    tenant = params["tenant"]
    dc = params["dc"]
    site = params["site"]
    company_name = params.get("name", tenant)
    query = params.get("query", "android")
    url = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

    jobs = []
    offset = 0
    total = None
    while total is None or offset < min(total, MAX_RESULTS):
        r = requests.post(
            url,
            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": query},
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        total = data.get("total", 0)
        postings = data.get("jobPostings", [])
        if not postings:
            break
        jobs.extend(normalize(p, tenant, dc, site, company_name) for p in postings)
        offset += PAGE_SIZE
    return jobs
