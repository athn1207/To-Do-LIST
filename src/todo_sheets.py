from __future__ import annotations

import uuid
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


def open_first_worksheet(credentials_path: str, spreadsheet_id: str) -> gspread.Worksheet:
    path = Path(credentials_path)
    if not path.is_file():
        raise FileNotFoundError(f"認証JSONが見つかりません: {path.resolve()}")
    creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id.strip())
    return sh.sheet1


def list_tasks(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()


def add_task(ws: gspread.Worksheet, title: str, content: str, due: str) -> str:
    rid = str(uuid.uuid4())
    ws.append_row([rid, title, content, due], value_input_option="USER_ENTERED")
    return rid


def _row_index_for_id(ws: gspread.Worksheet, task_id: str) -> int | None:
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row and row[0] == task_id:
            return i
    return None


def update_task(ws: gspread.Worksheet, task_id: str, title: str, content: str, due: str) -> bool:
    r = _row_index_for_id(ws, task_id)
    if r is None:
        return False
    ws.update(range_name=f"A{r}:D{r}", values=[[task_id, title, content, due]], value_input_option="USER_ENTERED")
    return True


def delete_task(ws: gspread.Worksheet, task_id: str) -> bool:
    r = _row_index_for_id(ws, task_id)
    if r is None:
        return False
    ws.delete_rows(r)
    return True
