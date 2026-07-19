# Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
# slug is visible in the company's jobs.ashbyhq.com/{slug} URL.
# Verified response shape (2026-07): {"jobs": [{"id", "title", "location",
# "jobUrl", "publishedAt", ...}]}
import requests

from .base import HEADERS, Job


def normalize(raw: dict, company: str) -> Job:
    return Job(
        job_id=f"ashby_{raw['id']}",
        title=raw["title"],
        company=company,
        url=raw["jobUrl"],
        location=raw.get("location"),
        posted_date=raw.get("publishedAt"),
    )


def fetch(params: dict) -> list[Job]:
    slug = params["slug"]
    company = params.get("name", slug)
    r = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return [normalize(j, company) for j in r.json().get("jobs", [])]
