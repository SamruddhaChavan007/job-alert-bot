from datetime import UTC, datetime

import config
from connectors import CONNECTORS
from filters import is_relevant, is_us_location
from notifier import get_reaction_status, post_error, post_job
from sheets import append_job, update_status
from state import load_state, save_state


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def log_error(message: str) -> None:
    print(f"[error] {message}")
    post_error(f"⚠️ {message}")


def run() -> None:
    companies = config.load_companies()
    state = load_state()

    all_jobs = []
    for c in companies:
        if not c.get("enabled", True):
            continue
        connector = CONNECTORS.get(c["connector"])
        if connector is None:
            log_error(f"{c['name']}: unknown connector '{c['connector']}'")
            continue
        try:
            all_jobs.extend(connector(c))
        except Exception as e:
            log_error(f"{c['name']} connector failed: {e}")

    relevant = [j for j in all_jobs if is_relevant(j) and is_us_location(j)]
    new_jobs = [j for j in relevant if j.job_id not in state]

    for job in new_jobs:
        company_cfg = next((c for c in companies if c["name"] == job.company), {})
        channel_id = company_cfg.get("discord_channel_id")
        msg_id = post_job(job, channel_id)
        first_seen = now_iso()
        row = append_job(job, first_seen)
        state[job.job_id] = {
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "first_seen": first_seen,
            "discord_message_id": msg_id,
            "discord_channel_id": channel_id,
            "sheet_row": row,
            "status": "new",
        }

    for job_id, record in state.items():
        if record["status"] in ("new", "opened"):
            new_status = get_reaction_status(
                record["discord_message_id"], record.get("discord_channel_id")
            )
            if new_status and new_status != record["status"]:
                record["status"] = new_status
                update_status(record["sheet_row"], new_status)

    save_state(state)
    print(f"processed {len(new_jobs)} new jobs")


if __name__ == "__main__":
    run()
