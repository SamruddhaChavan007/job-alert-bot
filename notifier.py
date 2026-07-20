import time

import requests

import config
from connectors.base import Job

API_BASE = "https://discord.com/api/v10"
MAX_RETRIES = 5

REACTION_STATUS_MAP = {
    "👀": "opened",
    "✅": "applied",
    "❌": "skipped",
}


def _headers() -> dict:
    return {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}


def _channel_id(job: Job, override: str | None) -> str:
    return override or config.DISCORD_CHANNEL_ID


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    r = None
    for attempt in range(MAX_RETRIES):
        r = requests.request(method, url, headers=_headers(), timeout=15, **kwargs)
        if r.status_code != 429:
            return r
        retry_after = r.json().get("retry_after", 1) if r.content else 1
        time.sleep(retry_after + 0.25)
    return r


def post_job(job: Job, channel_id: str | None = None) -> str:
    cid = _channel_id(job, channel_id)
    r = _request_with_retry(
        "POST",
        f"{API_BASE}/channels/{cid}/messages",
        json={
            "content": (
                f"**{job.title}** — {job.company}\n"
                f"{job.location or 'Location not listed'}\n{job.url}"
            )
        },
    )
    r.raise_for_status()
    return r.json()["id"]


def delete_message(message_id: str, channel_id: str | None = None) -> None:
    cid = channel_id or config.DISCORD_CHANNEL_ID
    try:
        _request_with_retry("DELETE", f"{API_BASE}/channels/{cid}/messages/{message_id}")
    except Exception:
        pass  # best-effort rollback — a failure here shouldn't mask the original error


def post_error(message: str) -> None:
    # error reporting must never itself crash the caller — a failure here
    # (e.g. the errors channel is also rate-limited) would otherwise break
    # the per-company/per-job isolation the rest of the pipeline relies on.
    if not config.BOT_ERRORS_CHANNEL_ID:
        return
    try:
        r = _request_with_retry(
            "POST",
            f"{API_BASE}/channels/{config.BOT_ERRORS_CHANNEL_ID}/messages",
            json={"content": message},
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[error] failed to post to bot-errors channel: {e}")


def get_reaction_status(message_id: str, channel_id: str | None = None) -> str | None:
    cid = channel_id or config.DISCORD_CHANNEL_ID
    for emoji, status in REACTION_STATUS_MAP.items():
        r = _request_with_retry(
            "GET", f"{API_BASE}/channels/{cid}/messages/{message_id}/reactions/{emoji}"
        )
        if r.status_code == 200 and r.json():
            return status
    return None
