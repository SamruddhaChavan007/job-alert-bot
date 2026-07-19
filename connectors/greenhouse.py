# Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
# slug is visible in the company's boards.greenhouse.io/{slug} URL.
# Verified response shape (2026-07): {"jobs": [{"id", "title", "location": {"name"},
# "absolute_url", "updated_at", ...}]}
import requests

from .base import HEADERS, Job


def normalize(raw: dict, company: str) -> Job:
    return Job(
        job_id=f"greenhouse_{raw['id']}",
        title=raw["title"],
        company=company,
        url=raw["absolute_url"],
        location=(raw.get("location") or {}).get("name"),
        posted_date=raw.get("updated_at"),
    )


def fetch(params: dict) -> list[Job]:
    slug = params["slug"]
    company = params.get("name", slug)
    r = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        params={"content": "true"},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return [normalize(j, company) for j in r.json().get("jobs", [])]
