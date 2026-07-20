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


def _post_with_retry(url: str, json_body: dict) -> requests.Response:
    for attempt in range(MAX_RETRIES):
        r = requests.post(url, headers=_headers(), json=json_body, timeout=15)
        if r.status_code != 429:
            return r
        retry_after = r.json().get("retry_after", 1) if r.content else 1
        time.sleep(retry_after + 0.25)
    r.raise_for_status()
    return r


def post_job(job: Job, channel_id: str | None = None) -> str:
    cid = _channel_id(job, channel_id)
    r = _post_with_retry(
        f"{API_BASE}/channels/{cid}/messages",
        {
            "content": (
                f"**{job.title}** — {job.company}\n"
                f"{job.location or 'Location not listed'}\n{job.url}"
            )
        },
    )
    r.raise_for_status()
    return r.json()["id"]


def post_error(message: str) -> None:
    if not config.BOT_ERRORS_CHANNEL_ID:
        return
    _post_with_retry(
        f"{API_BASE}/channels/{config.BOT_ERRORS_CHANNEL_ID}/messages",
        {"content": message},
    )


def get_reaction_status(message_id: str, channel_id: str | None = None) -> str | None:
    cid = channel_id or config.DISCORD_CHANNEL_ID
    for emoji, status in REACTION_STATUS_MAP.items():
        r = requests.get(
            f"{API_BASE}/channels/{cid}/messages/{message_id}/reactions/{emoji}",
            headers=_headers(),
            timeout=15,
        )
        if r.status_code == 200 and r.json():
            return status
    return None
