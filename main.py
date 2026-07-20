from collections import defaultdict
from datetime import UTC, datetime, timedelta

import config
from connectors import CONNECTORS
from filters import (
    is_recent,
    is_us_location,
    is_within_experience_range,
    job_category,
    sort_by_recency,
    time_ago,
)
from notifier import POLL_DURATION_HOURS, delete_message, get_job_status, post_error, post_job
from sheets import append_job, update_status
from state import load_state, save_state

# Circuit breaker: if a single run finds more new jobs than this in one
# category, post only the first N and leave the rest untracked so they drip
# in over subsequent runs instead of flooding the channel all at once. This
# is the main defense against cold-start floods (a new company/category with
# a large pre-existing backlog matching on its first-ever run) -- reproduced
# live: backfilling a new SWE category posted 246 jobs in one run.
MAX_NEW_JOBS_PER_CATEGORY_PER_RUN = 20

# once a job's poll expires, voting is permanently impossible -- stop
# checking it (bounds sync workload as state grows) and mark it archived
# instead of leaving it stuck on "new" forever with no way to tell "still
# pending" from "nobody ever responded".
POLL_EXPIRY = timedelta(hours=POLL_DURATION_HOURS)


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

    CATEGORY_CHANNELS = {"android": config.DISCORD_CHANNEL_ID, "swe": config.DEV_JOBS_CHANNEL_ID}

    categorized = ((j, job_category(j)) for j in all_jobs)
    relevant = [
        (j, cat) for j, cat in categorized
        if cat is not None and is_us_location(j) and is_within_experience_range(j) and is_recent(j)
    ]
    new_jobs = [(j, cat) for j, cat in relevant if j.job_id not in state]

    by_category = defaultdict(list)
    for j, cat in new_jobs:
        by_category[cat].append(j)
    capped_new_jobs = []
    for cat, jobs in by_category.items():
        jobs = sort_by_recency(jobs)
        if len(jobs) > MAX_NEW_JOBS_PER_CATEGORY_PER_RUN:
            log_error(
                f"{cat}: found {len(jobs)} new jobs in one run (cap is "
                f"{MAX_NEW_JOBS_PER_CATEGORY_PER_RUN}) -- posting first "
                f"{MAX_NEW_JOBS_PER_CATEGORY_PER_RUN}, remainder will drip in over subsequent runs"
            )
            jobs = jobs[:MAX_NEW_JOBS_PER_CATEGORY_PER_RUN]
        capped_new_jobs.extend((j, cat) for j in jobs)
    new_jobs = capped_new_jobs

    try:
        posted = 0
        for job, category in new_jobs:
            company_cfg = next((c for c in companies if c["name"] == job.company), {})
            channel_id = company_cfg.get("discord_channel_id") or CATEGORY_CHANNELS.get(category)
            msg_id = None
            try:
                msg_id = post_job(job, channel_id, time_ago(job.posted_date))
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
                posted += 1
            except Exception as e:
                # posting to Discord can succeed before a later step (Sheets)
                # fails -- roll back the message so the job isn't left
                # orphaned (no state entry) and reposted as a duplicate next run.
                if msg_id is not None and job.job_id not in state:
                    delete_message(msg_id, channel_id)
                log_error(f"failed to post/log job {job.job_id}: {e}")

        for job_id, record in state.items():
            if record["status"] in ("new", "opened"):
                try:
                    first_seen = datetime.fromisoformat(record["first_seen"])
                    if datetime.now(UTC) - first_seen > POLL_EXPIRY:
                        record["status"] = "archived"
                        update_status(record["sheet_row"], "archived")
                        continue
                    new_status = get_job_status(
                        record["discord_message_id"], record.get("discord_channel_id")
                    )
                    if new_status and new_status != record["status"]:
                        record["status"] = new_status
                        update_status(record["sheet_row"], new_status)
                except Exception as e:
                    log_error(f"failed to sync status for {job_id}: {e}")
    finally:
        # always persist whatever progress was made, even if the loop above
        # raised — otherwise a crash mid-run leaves posted jobs untracked in
        # state and they get reposted as duplicates on the next run.
        save_state(state)

    print(f"processed {posted} new jobs")


if __name__ == "__main__":
    run()
