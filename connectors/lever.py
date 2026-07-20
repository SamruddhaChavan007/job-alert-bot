# Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
# slug is visible in the company's jobs.lever.co/{slug} URL.
# Verified response shape (2026-07): [{"id", "text", "hostedUrl", "categories":
# {"location", ...}, "createdAt" (ms epoch), ...}]
import requests

from .base import HEADERS, Job


def normalize(raw: dict, company: str) -> Job:
    return Job(
        job_id=f"lever_{raw['id']}",
        title=raw["text"],
        company=company,
        url=raw["hostedUrl"],
        location=(raw.get("categories") or {}).get("location"),
        posted_date=raw.get("createdAt"),
    )


def fetch(params: dict) -> list[Job]:
    slug = params["slug"]
    company = params.get("name", slug)
    r = requests.get(
        f"https://api.lever.co/v0/postings/{slug}",
        params={"mode": "json"},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return [normalize(j, company) for j in r.json()]
