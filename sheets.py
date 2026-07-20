import json
import time
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from connectors.base import Job

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_RANGE = "Sheet1"
COLUMNS = ["Job ID", "Title", "Company", "URL", "Date Found", "Status", "Notes"]
MAX_RETRIES = 5
RETRYABLE_STATUSES = {429, 500, 502, 503}


def _format_date(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d - %I:%M %p")

_service = None


def _sheets():
    global _service
    if _service is None:
        creds = Credentials.from_service_account_info(
            json.loads(config.GOOGLE_SHEETS_CREDENTIALS), scopes=SCOPES
        )
        _service = build("sheets", "v4", credentials=creds).spreadsheets()
    return _service


def _execute_with_retry(request):
    for attempt in range(MAX_RETRIES):
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status
            if status in RETRYABLE_STATUSES and attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)  # Sheets errors don't carry a retry_after
                continue
            raise


def append_job(job: Job, first_seen: str) -> int:
    row = [job.job_id, job.title, job.company, job.url, _format_date(first_seen), "new", ""]
    request = _sheets().values().append(
        spreadsheetId=config.GOOGLE_SHEET_ID,
        range=SHEET_RANGE,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    )
    result = _execute_with_retry(request)
    updated_range = result["updates"]["updatedRange"]
    row_number = int("".join(filter(str.isdigit, updated_range.split("!")[1].split(":")[0])))
    return row_number


def update_status(row: int, status: str) -> None:
    status_col = COLUMNS.index("Status")
    col_letter = chr(ord("A") + status_col)
    request = _sheets().values().update(
        spreadsheetId=config.GOOGLE_SHEET_ID,
        range=f"{SHEET_RANGE}!{col_letter}{row}",
        valueInputOption="RAW",
        body={"values": [[status]]},
    )
    _execute_with_retry(request)
