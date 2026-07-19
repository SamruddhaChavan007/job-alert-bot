import requests

import config
from connectors.base import Job

API_BASE = "https://discord.com/api/v10"

REACTION_STATUS_MAP = {
    "👀": "opened",
    "✅": "applied",
    "❌": "skipped",
}


def _headers() -> dict:
    return {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}


def _channel_id(job: Job, override: str | None) -> str:
    return override or config.DISCORD_CHANNEL_ID


def post_job(job: Job, channel_id: str | None = None) -> str:
    cid = _channel_id(job, channel_id)
    r = requests.post(
        f"{API_BASE}/channels/{cid}/messages",
        headers=_headers(),
        json={
            "content": (
                f"**{job.title}** — {job.company}\n"
                f"{job.location or 'Location not listed'}\n{job.url}"
            )
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["id"]


def post_error(message: str) -> None:
    if not config.BOT_ERRORS_CHANNEL_ID:
        return
    requests.post(
        f"{API_BASE}/channels/{config.BOT_ERRORS_CHANNEL_ID}/messages",
        headers=_headers(),
        json={"content": message},
        timeout=15,
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
