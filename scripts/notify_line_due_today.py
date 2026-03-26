from __future__ import annotations

import json
import os
from datetime import date

import gspread
import requests
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
STATUS_DONE = "完了"


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v


def _parse_due(due_raw: str) -> date | None:
    s = str(due_raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _build_message(tasks: list[dict], today: date) -> str:
    lines = [f"【Todo通知】{today.isoformat()} が期日の未完了タスク"]
    for t in tasks:
        title = str(t.get("タイトル", "")).strip()
        if title:
            lines.append(f"・{title}")
    return "\n".join(lines) if len(lines) > 1 else f"【Todo通知】{today.isoformat()} が期日の未完了タスクはありません"


def _open_spreadsheet(service_account_json: str, spreadsheet_id: str) -> gspread.Spreadsheet:
    info = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id.strip())


def _get_or_create_notification_sheet(sh: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        ws = sh.worksheet("Notification")
    except WorksheetNotFound:
        ws = sh.add_worksheet(title="Notification", rows=50, cols=2)
        ws.append_row(["key", "value"])
    return ws


def _read_last_sent(notify_ws: gspread.Worksheet) -> str | None:
    values = notify_ws.get_all_values()
    if len(values) < 2:
        return None
    # header: [key, value]
    header = values[0]
    try:
        key_idx = header.index("key")
        val_idx = header.index("value")
    except ValueError:
        key_idx, val_idx = 0, 1
    for row in values[1:]:
        if len(row) > max(key_idx, val_idx) and row[key_idx] == "last_line_sent_date":
            return row[val_idx].strip() or None
    return None


def _update_last_sent(notify_ws: gspread.Worksheet, today_iso: str) -> None:
    values = notify_ws.get_all_values()
    if not values:
        notify_ws.append_row(["key", "value"])
        values = notify_ws.get_all_values()

    header = values[0]
    try:
        key_idx = header.index("key")
        val_idx = header.index("value")
    except ValueError:
        key_idx, val_idx = 0, 1

    # try update existing row
    for i, row in enumerate(values[1:], start=2):  # 1-based row index in Sheets
        if len(row) > key_idx and row[key_idx] == "last_line_sent_date":
            notify_ws.update_cell(i, val_idx + 1, today_iso)
            return

    # otherwise append
    notify_ws.append_row(["last_line_sent_date", today_iso])


def _send_line_broadcast(token: str, text: str) -> None:
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"messages": [{"type": "text", "text": text}]}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


def main() -> None:
    spreadsheet_id = _env("SPREADSHEET_ID")
    gcp_sa_json = _env("GCP_SERVICE_ACCOUNT_JSON")
    line_token = _env("LINE_CHANNEL_ACCESS_TOKEN")

    today = date.today()
    sh = _open_spreadsheet(gcp_sa_json, spreadsheet_id)
    ws = sh.sheet1

    records = ws.get_all_records()
    tasks = [
        r
        for r in records
        if _parse_due(r.get("期日", "")) == today and str(r.get("ステータス", "")).strip() != STATUS_DONE
    ]

    if not tasks:
        print("No due-today pending tasks. Nothing to send.")
        return

    notify_ws = _get_or_create_notification_sheet(sh)
    last_sent = _read_last_sent(notify_ws)
    if last_sent == today.isoformat():
        print("Already sent today. Skip.")
        return

    text = _build_message(tasks, today)
    _send_line_broadcast(line_token, text)
    _update_last_sent(notify_ws, today.isoformat())
    print(f"Sent LINE notification for {today.isoformat()}. Tasks: {len(tasks)}")


if __name__ == "__main__":
    main()

