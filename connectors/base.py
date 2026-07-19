from dataclasses import dataclass


@dataclass
class Job:
    job_id: str          # unique, prefixed per company e.g. "google_123456"
    title: str
    company: str
    url: str
    location: str | None
    posted_date: str | None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
