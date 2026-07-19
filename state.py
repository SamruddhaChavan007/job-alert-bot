import json

import requests

import config

STATE_FILENAME = "state.json"
API_URL_TMPL = "https://api.github.com/gists/{gist_id}"


def _headers() -> dict:
    return {
        "Authorization": f"token {config.GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def load_state() -> dict:
    r = requests.get(API_URL_TMPL.format(gist_id=config.GIST_ID), headers=_headers(), timeout=15)
    r.raise_for_status()
    content = r.json()["files"][STATE_FILENAME]["content"]
    return json.loads(content)


def save_state(state: dict) -> None:
    payload = {"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}}
    r = requests.patch(
        API_URL_TMPL.format(gist_id=config.GIST_ID),
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
