import time

import requests

import config
from connectors.base import Job

API_BASE = "https://discord.com/api/v10"
MAX_RETRIES = 5
POLL_DURATION_HOURS = 72  # 3 days

# legacy: messages posted before poll-based status tracking used plain
# reactions -- kept so those older messages keep syncing correctly.
REACTION_STATUS_MAP = {
    "👀": "opened",
    "✅": "applied",
    "❌": "skipped",
}

POLL_ANSWER_STATUS_MAP = {
    "Viewed": "opened",
    "Applied": "applied",
    "Skipped": "skipped",
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


def post_job(job: Job, channel_id: str | None = None, posted_ago: str | None = None) -> str:
    cid = _channel_id(job, channel_id)
    lines = [f"**{job.title}** — {job.company}", job.location or "Location not listed"]
    if posted_ago:
        lines.append(f"Posted {posted_ago}")
    lines.append(job.url)
    r = _request_with_retry(
        "POST",
        f"{API_BASE}/channels/{cid}/messages",
        json={
            "content": "\n".join(lines),
            "poll": {
                "question": {"text": "Status?"},
                "answers": [
                    {"poll_media": {"text": "Applied"}},
                    {"poll_media": {"text": "Skipped"}},
                    {"poll_media": {"text": "Viewed"}},
                ],
                "duration": POLL_DURATION_HOURS,
                "allow_multiselect": False,
            },
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


def _poll_status(poll: dict) -> str | None:
    answers = {a["answer_id"]: a["poll_media"]["text"] for a in poll.get("answers", [])}
    counts = (poll.get("results") or {}).get("answer_counts", [])
    for ac in counts:
        if ac.get("count", 0) > 0:
            status = POLL_ANSWER_STATUS_MAP.get(answers.get(ac["id"]))
            if status:
                return status
    return None


def _reaction_status(reactions: list) -> str | None:
    present = {rx["emoji"]["name"] for rx in reactions if rx.get("count", 0) > 0}
    for emoji, status in REACTION_STATUS_MAP.items():
        if emoji in present:
            return status
    return None


def get_job_status(message_id: str, channel_id: str | None = None) -> str | None:
    # fetch the message once and read its status from whichever mechanism it
    # uses -- new messages carry a poll, messages posted before poll-based
    # tracking rolled out only have reactions. One request either way.
    cid = channel_id or config.DISCORD_CHANNEL_ID
    r = _request_with_retry("GET", f"{API_BASE}/channels/{cid}/messages/{message_id}")
    if r.status_code != 200:
        return None
    data = r.json()
    poll = data.get("poll")
    if poll:
        return _poll_status(poll)
    return _reaction_status(data.get("reactions") or [])
