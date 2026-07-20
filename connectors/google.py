# Endpoint: no public JSON API. Google Careers' actual job-search API
# (google.internal.onegoogle.asyncdata.v1.AsyncDataService) is an internal,
# undocumented RPC framework that requires an authenticated personal Google
# session + a short-lived anti-CSRF token -- unsafe and unstable to automate.
# Job listings ARE server-rendered directly in the public, unauthenticated
# search-results HTML, so this connector scrapes that page instead.
# Verified live (2026-07): https://www.google.com/about/careers/applications/jobs/results/?q=<query>
import html
import re

import requests

from .base import HEADERS, Job

SEARCH_URL = "https://www.google.com/about/careers/applications/jobs/results/"

_JOB_RE = re.compile(
    r'<p class="l103df">([^<]+?)\s*\|\s*<span class="pwO9Dc">(.*?)</span></p>.*?'
    r'href="jobs/results/(\d+)-[^"?]*\?[^"]*"\s*aria-label="Learn more about ([^"]+)"',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_DUPLICATE_MORE_RE = re.compile(r"(; \+\d+ more)(?:; \+\d+ more)+")


def _clean_location(loc_html: str) -> str:
    text = _TAG_RE.sub("", loc_html)
    text = html.unescape(text).strip()
    return _DUPLICATE_MORE_RE.sub(r"\1", text)


def normalize(job_id: str, title: str, location: str) -> Job:
    return Job(
        job_id=f"google_{job_id}",
        title=html.unescape(title),
        company="Google",
        url=f"https://www.google.com/about/careers/applications/jobs/results/{job_id}",
        location=location,
        posted_date=None,
    )


def fetch(params: dict) -> list[Job]:
    query = params.get("query", "android")
    r = requests.get(SEARCH_URL, params={"q": query}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    matches = _JOB_RE.findall(r.text)
    return [
        normalize(job_id, title, _clean_location(loc_html))
        for _company, loc_html, job_id, title in matches
    ]
