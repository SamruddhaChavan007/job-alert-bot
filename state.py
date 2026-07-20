import json
import time

import requests

import config

STATE_FILENAME = "state.json"
API_URL_TMPL = "https://api.github.com/gists/{gist_id}"
MAX_RETRIES = 5
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _headers() -> dict:
    return {
        "Authorization": f"token {config.GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _request_with_retry(method: str, **kwargs) -> requests.Response:
    r = None
    for attempt in range(MAX_RETRIES):
        r = requests.request(
            method, API_URL_TMPL.format(gist_id=config.GIST_ID),
            headers=_headers(), timeout=15, **kwargs,
        )
        if r.status_code not in RETRYABLE_STATUSES:
            return r
        time.sleep(2**attempt)  # GitHub errors don't carry a retry_after
    return r


def load_state() -> dict:
    r = _request_with_retry("GET")
    r.raise_for_status()
    content = r.json()["files"][STATE_FILENAME]["content"]
    return json.loads(content)


def save_state(state: dict) -> None:
    payload = {"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}}
    r = _request_with_retry("PATCH", json=payload)
    r.raise_for_status()
