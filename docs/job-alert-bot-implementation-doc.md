# Job Alert Bot — Technical Implementation Doc

## 1. Goal
Poll career pages of target companies (Google, Amazon, etc.) for new Android/Kotlin job postings, notify instantly via Discord, log to Google Sheets for tracking, and stay $0 cost. Architecture: modular monolith, designed so a web dashboard can be layered on later without a rewrite.

---

## 2. Architecture Overview

```
                ┌─────────────────────────────┐
                │   GitHub Actions (cron)      │
                │   */5 * * * *  (public repo) │
                └──────────────┬──────────────┘
                               │ triggers
                               ▼
                        ┌────────────┐
                        │  main.py    │  (orchestrator)
                        └──────┬─────┘
        ┌──────────────┬──────┼───────────┬───────────────┐
        ▼              ▼      ▼           ▼               ▼
 companies.json   connectors/  state.py  notifier.py   sheets.py
 (config)         google.py    (Gist     (Discord bot) (Google
                  amazon.py    read/                    Sheets
                  ...          write)                   logger)
                                  │           │               │
                                  ▼           ▼               ▼
                           Secret Gist   Discord channel  Google Sheet
                           (dedup store)  (real-time push  (browsable
                                           + reactions)     tracker)
```

**Flow per run:**
1. Load `companies.json`
2. For each enabled company → call its connector → get normalized job list
3. Filter jobs by keyword (android, kotlin, mobile, jetpack compose)
4. Load current state from secret Gist (`{job_id: {...}}`)
5. Diff → find new job IDs
6. For each new job:
   - Post to Discord via bot API (get back `message_id`)
   - Append row to Google Sheet
   - Add to state with `status: "new"`
7. For jobs already in state with status `new`/`opened` → check Discord reactions → update status in state + Sheet
8. Save updated state back to Gist

---

## 3. Repo Structure

```
job-alert-bot/                      (PUBLIC repo — unlimited free Actions minutes)
├── companies.json                  # editable list of companies to track
├── main.py                         # orchestrator entrypoint
├── requirements.txt
├── connectors/
│   ├── __init__.py
│   ├── base.py                     # shared Job dataclass + interface
│   ├── google.py
│   ├── amazon.py
│   └── ...                         # one file per company added later
├── state.py                        # Gist read/write helpers
├── notifier.py                     # Discord bot posting + reaction checks
├── sheets.py                       # Google Sheets read/write helpers
├── filters.py                      # keyword filtering logic
├── config.py                       # loads env vars/secrets
└── .github/
    └── workflows/
        └── job-watch.yml
```

State (`state.json` equivalent) lives in a **secret GitHub Gist**, NOT in this repo — keeps job-tracking history out of public view while code stays public and free to run.

---

## 4. Data Models

### Job (internal, normalized — used everywhere after a connector runs)
```python
@dataclass
class Job:
    job_id: str          # unique, prefixed per company e.g. "google_123456"
    title: str
    company: str
    url: str
    location: str | None
    posted_date: str | None
```

### `companies.json`
Two kinds of entries: **custom** (bespoke API per company, e.g. Google/Amazon) and **ATS-based** (generic connector shared by any company on that ATS — Greenhouse, Ashby). ATS-based entries only need a `slug`, no custom endpoint/params.

```json
{
  "companies": [
    {
      "name": "Google",
      "enabled": true,
      "career_page": "https://careers.google.com",
      "endpoint": "https://careers.google.com/api/v3/search/",
      "params": { "q": "android", "employment_type": "FULL_TIME" },
      "connector": "google"
    },
    {
      "name": "Amazon",
      "enabled": true,
      "career_page": "https://amazon.jobs",
      "endpoint": "https://www.amazon.jobs/en/search.json",
      "params": { "base_query": "android kotlin", "category": "software-development" },
      "connector": "amazon"
    },
    {
      "name": "Stripe",
      "enabled": true,
      "ats": "greenhouse",
      "slug": "stripe",
      "connector": "greenhouse",
      "discord_channel_id": null
    },
    {
      "name": "Notion",
      "enabled": true,
      "ats": "ashby",
      "slug": "notion",
      "connector": "ashby",
      "discord_channel_id": null
    }
  ]
}
```
`discord_channel_id`: optional per-company override. If `null`, falls back to the default `DISCORD_CHANNEL_ID` env var. Lets you route specific companies to specific channels later (e.g. big tech vs. startups) without any code changes.

### State (in secret Gist, `state.json`)
```json
{
  "google_123456": {
    "title": "Android Engineer II",
    "company": "Google",
    "url": "https://...",
    "first_seen": "2026-07-19T10:05:00Z",
    "discord_message_id": "1234567890",
    "sheet_row": 42,
    "status": "new"
  }
}
```
`status` progresses: `new → opened → applied` (or `skipped`), driven by Discord reactions.

---

## 5. Component Details

### 5.1 Connectors (`connectors/*.py`)
Each connector implements one function with a consistent signature:
```python
def fetch(params: dict) -> list[Job]:
    """Call the company's JSON endpoint, return normalized Job list (unfiltered)."""
```
Wrapped in `main.py` with per-company `try/except` so one broken connector (site redesign, schema change) doesn't kill the whole run — log the failure and continue with the rest.

**Finding each endpoint:** DevTools → Network tab → XHR/Fetch → search a keyword on the career page → find the JSON response → note URL + params. Document this per-company in a comment at the top of each connector file since endpoints can shift.

**Custom connectors** (one per company, bespoke API): `google.py`, `amazon.py` — needed for companies with their own in-house career site/API.

**Generic ATS connectors** (one connector, reused across many companies via `slug`): most mid-size tech companies and startups run their job board on a shared ATS platform with a predictable, documented, public JSON endpoint — no reverse-engineering needed.

```python
# connectors/greenhouse.py
def fetch(slug: str) -> list[Job]:
    r = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        params={"content": "true"},   # include full description for better filtering
        headers=HEADERS
    )
    return [normalize(j, "greenhouse") for j in r.json().get("jobs", [])]
```
```python
# connectors/ashby.py
def fetch(slug: str) -> list[Job]:
    r = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        headers=HEADERS
    )
    return [normalize(j, "ashby") for j in r.json().get("jobs", [])]
```
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` — slug is visible in the company's `boards.greenhouse.io/{slug}` URL
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{slug}` — slug is visible in the company's `jobs.ashbyhq.com/{slug}` URL

Adding a new Greenhouse/Ashby company going forward = **one new entry in `companies.json`, zero new code**. This is the highest-leverage way to scale company coverage.

### 5.2 `filters.py`
```python
KEYWORDS = ["android", "kotlin", "jetpack compose", "mobile developer"]

def is_relevant(job: Job) -> bool:
    text = job.title.lower()
    return any(k in text for k in KEYWORDS)
```

### 5.2.1 Location filtering (US-only)
Not every source supports server-side location filtering, so this needs two layers:

**Layer 1 — source-level params, where supported (cheaper, less data to pull/parse):**
- Google Careers: add a location param to `params` in `companies.json`, e.g. `"location": "United States"`
- Amazon Jobs: add `"normalized_country_code": "USA"` to `params`
- Greenhouse / Ashby: their public job board endpoints generally do **not** support server-side location filtering — all locations come back regardless, so Layer 2 is required for these

**Layer 2 — universal fallback in `filters.py` (required regardless of source):**
```python
US_INDICATORS = ["united states", "usa", "u.s.",
                  ", ca", ", ny", ", tx", ", wa", ", il", ", ma", ", az"]  # extend as needed

def is_us_location(job: Job) -> bool:
    if not job.location:
        return False  # exclude if location is missing/unclear — safer default than including
    loc = job.location.lower()
    return any(ind in loc for ind in US_INDICATORS)
```
Most location strings follow a `"City, ST"` or `"City, State, Country"` pattern — matching state abbreviations after a comma tends to be more reliable than trying to match every phrasing of "United States." Validate the actual indicator list against real responses once connectors are live, since formatting varies by company/ATS.

**Remote roles:** location strings vary a lot (`"Remote - US"`, `"Remote, USA"`, `"United States (Remote)"`, unqualified `"Remote"`/`"Global"`). The US-indicator match above naturally includes qualified remote-US postings while excluding unqualified `"Remote"`/`"Global"` ones — decide if that's the behavior you want, or add an explicit `include_unqualified_remote: false` flag if you'd rather be stricter.

`is_relevant()` and `is_us_location()` are combined in `main.py`'s filtering step — a job must pass both to be treated as new.


- Uses a **GitHub Personal Access Token** (scope: `gist`) stored as a secret
- `load_state() -> dict` — GET the gist file, `json.loads`
- `save_state(state: dict)` — PATCH the gist file with updated JSON
- Gist is created once manually (secret/unlisted), its ID stored as a secret too

### 5.4 `notifier.py` — Discord
- Uses a **Discord bot token** (not a plain webhook) so responses include `message_id`
- `post_job(job: Job) -> str` → POST to `https://discord.com/api/v10/channels/{CHANNEL_ID}/messages`, returns message ID
- `get_reaction_status(message_id: str) -> str | None` → GET reactions on that message, map emoji → status:
  - 👀 → `opened`
  - ✅ → `applied`
  - ❌ → `skipped`
- Bot needs `Send Messages`, `Read Message History`, `Add Reactions` permissions in the server

### 5.4.1 Discord channel structure
Start with **2 channels**:
| Channel | Purpose |
|---|---|
| `#job-alerts` | Default target — all new job postings unless a company overrides it |
| `#bot-errors` | Connector failures logged here, so a silently broken connector (e.g. an ATS API schema change) gets noticed instead of just quietly producing zero alerts |

Optional scale-up (once volume/noise justifies it, e.g. 15-20+ companies): split `#job-alerts` further (e.g. `#job-alerts-bigtech` vs `#job-alerts-startups`) using the per-company `discord_channel_id` field in `companies.json` — `notifier.py` just reads that field and falls back to the default `DISCORD_CHANNEL_ID` env var when null. No architecture change, just a config value and one `if`.

### 5.5 `sheets.py` — Google Sheets logging
- Google Cloud **service account** (free), Sheets API enabled, JSON key stored as a secret
- Sheet shared with the service account's email
- `append_job(job: Job) -> int` → appends a row, returns row number (stored in state for later status updates)
- `update_status(row: int, status: str)` → updates the Status column for that row
- Columns: `Job ID | Title | Company | URL | Date Found | Status | Notes`
- `Notes` column is manual-only — never touched by the script, safe for you to annotate freely

### 5.6 `main.py` — Orchestrator
```python
def run():
    companies = load_companies("companies.json")
    state = load_state()

    all_jobs = []
    for c in companies:
        if not c.get("enabled", True):
            continue
        try:
            jobs = CONNECTORS[c["connector"]].fetch(c["params"])
            all_jobs.extend(jobs)
        except Exception as e:
            log_error(f"{c['name']} connector failed: {e}")

    relevant = [j for j in all_jobs if is_relevant(j)]
    new_jobs = [j for j in relevant if j.job_id not in state]

    for job in new_jobs:
        msg_id = post_job(job)
        row = append_job(job)
        state[job.job_id] = {
            "title": job.title, "company": job.company, "url": job.url,
            "first_seen": now_iso(), "discord_message_id": msg_id,
            "sheet_row": row, "status": "new"
        }

    # sync status from Discord reactions for anything not yet applied/skipped
    for job_id, record in state.items():
        if record["status"] in ("new", "opened"):
            new_status = get_reaction_status(record["discord_message_id"])
            if new_status and new_status != record["status"]:
                record["status"] = new_status
                update_status(record["sheet_row"], new_status)

    save_state(state)

if __name__ == "__main__":
    run()
```

---

## 6. Secrets (GitHub Actions → Settings → Secrets and variables → Actions)

| Secret name | Purpose |
|---|---|
| `GIST_TOKEN` | PAT with `gist` scope — read/write state Gist |
| `GIST_ID` | ID of the secret Gist holding `state.json` |
| `DISCORD_BOT_TOKEN` | Bot auth for posting + reading reactions |
| `DISCORD_CHANNEL_ID` | Target channel for job alerts |
| `GOOGLE_SHEETS_CREDENTIALS` | Service account JSON (as a string) |
| `GOOGLE_SHEET_ID` | Target spreadsheet ID |

None of these ever appear in code or logs — GitHub auto-masks secret values in Action logs.

---

## 7. GitHub Actions Workflow

```yaml
# .github/workflows/job-watch.yml
name: Job Watch
on:
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch: {}

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          GIST_TOKEN: ${{ secrets.GIST_TOKEN }}
          GIST_ID: ${{ secrets.GIST_ID }}
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_CHANNEL_ID: ${{ secrets.DISCORD_CHANNEL_ID }}
          GOOGLE_SHEETS_CREDENTIALS: ${{ secrets.GOOGLE_SHEETS_CREDENTIALS }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
```
Public repo → unlimited free minutes on standard runners, no budget math needed.

---

## 8. Guardrails
- 5-minute poll interval — safe, won't trigger rate-limiting/bot-detection
- Set a normal browser `User-Agent` header on all outbound requests
- Per-connector `try/except` — one company's API/schema change never breaks the whole run
- Log connector failures to a dedicated `#bot-errors` Discord channel (or just log to Action output) so silent breakage gets noticed
- Never print job titles/companies to public Action logs if that bothers you — keep log output generic (`"processed 3 new jobs"`)

---

## 9. Build Order (recommended sequence)
1. `connectors/google.py` + `connectors/amazon.py` — verify real endpoints, get raw JSON, write parsers
2. `state.py` — Gist create + read/write, test manually
3. `main.py` skeleton — wire connectors + filtering + state diff, no notifications yet (just print new jobs)
4. `notifier.py` — Discord bot setup, post_job, verify message appears in channel
5. Reaction-checking loop in `notifier.py` + `main.py` integration
6. `sheets.py` — service account setup, append_job, update_status
7. `.github/workflows/job-watch.yml` — wire it all into scheduled runs
8. Add more companies via `companies.json` + new connector files

---

## 10. Future: Web Dashboard (not now, documented for later)
- Swap Gist → **Supabase** (Postgres) as the source of truth once a dashboard is wanted
- Discord, Sheets, and dashboard all become read/write views into the same Supabase tables instead of the Gist being the quiet "real" store
- Frontend: lightweight React/Next.js app, free hosting on Vercel/Netlify, Supabase client SDK reads directly from the browser
- No rewrite needed — this is a storage swap, not an architecture change, because `state.py`'s interface (`load_state`/`save_state`) is already isolated behind a clean boundary

---

## 12. File Responsibility Rules

Keeps the modular monolith actually modular — each file has one job, and mixing concerns across files is the #1 way this kind of project turns into spaghetti. Rules below are boundaries to enforce as you write code, not just documentation.

### `companies.json`
**Should contain:** company name, enabled flag, connector type, slug or endpoint/params, optional `discord_channel_id`.
**Should NOT contain:** secrets, tokens, any logic, filtering keywords (those belong in `filters.py` — keep keyword rules global, not per-company, unless a real need arises).

### `main.py`
**Should contain:** orchestration only — call connectors, call filters, diff against state, call notifier/sheets, save state. The "what happens in what order."
**Should NOT contain:** HTTP request logic, JSON parsing details for any specific company/API, Discord/Sheets API specifics, keyword lists. If you're writing a `requests.get(...)` inside `main.py`, it belongs in a connector instead.

### `connectors/*.py`
**Should contain:** one `fetch()` per file, talking to exactly one API (or one ATS pattern), returning a list of normalized `Job` objects. All company/API-specific quirks (odd field names, pagination, nested JSON) stay contained here.
**Should NOT contain:** filtering logic (keyword matching), Discord/Sheets calls, state/dedup logic, anything about *what happens* to the jobs after they're fetched. A connector's only job is: raw API → clean `Job` list.

### `filters.py`
**Should contain:** keyword list, `is_relevant(job) -> bool`, any future filtering rules (location, seniority, etc).
**Should NOT contain:** fetching, notifying, or state logic. Pure function(s) only — same input always gives same output, no side effects, no network calls.

### `state.py`
**Should contain:** Gist read/write only — `load_state()`, `save_state()`. Treats state as an opaque dict; doesn't know what a "job" is beyond a key in that dict.
**Should NOT contain:** business logic about what counts as a new job (that's `main.py`'s diff step), Discord/Sheets calls, filtering.

### `notifier.py`
**Should contain:** Discord bot API calls only — `post_job()`, `get_reaction_status()`, emoji→status mapping.
**Should NOT contain:** state persistence, Sheets logic, filtering, connector logic. Doesn't decide *whether* to post — just posts what it's told to.

### `sheets.py`
**Should contain:** Google Sheets API calls only — `append_job()`, `update_status()`.
**Should NOT contain:** state persistence, Discord logic, filtering, decisions about which jobs to log. Same principle as `notifier.py` — a dumb, focused I/O layer.

### `config.py`
**Should contain:** reading env vars/secrets into typed constants (e.g. `DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]`), loading `companies.json`.
**Should NOT contain:** any actual API calls, business logic, or hardcoded secret values (secrets only ever come from env vars, never literals — even in local `.env` files that should stay gitignored and never committed).

### General rules across all files
- **No file other than `connectors/*.py` should know the shape of a raw API response.** Everything downstream only ever sees the normalized `Job` dataclass.
- **No file other than `notifier.py`/`sheets.py` should construct a Discord/Sheets API request.** If `main.py` is building a payload dict for Discord, that's misplaced.
- **Secrets only flow through `config.py`.** Other files import constants from there, never read `os.environ` directly — makes it obvious at a glance where all external config enters the system.
- **Side-effecting code (network calls, writes) stays out of `filters.py` and any future pure-logic files** — keeps them trivially testable without mocking anything.

---

## 13. Cost Summary
| Component | Cost |
|---|---|
| GitHub Actions (public repo) | $0, unlimited |
| GitHub Gist | $0 |
| Discord bot | $0 |
| Google Sheets API | $0 (personal-scale usage) |
| Company JSON endpoints | $0 (public, no auth) |
| **Total** | **$0/month** |
