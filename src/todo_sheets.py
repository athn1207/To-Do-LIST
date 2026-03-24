from __future__ import annotations

import uuid
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

STATUS_DONE = "完了"


def open_spreadsheet(credentials_path: str, spreadsheet_id: str) -> gspread.Spreadsheet:
    path = Path(credentials_path)
    if not path.is_file():
        raise FileNotFoundError(f"認証JSONが見つかりません: {path.resolve()}")
    creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id.strip())


def open_spreadsheet_from_service_account_info(
    service_account_info: dict,
    spreadsheet_id: str,
) -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id.strip())


def open_first_worksheet(credentials_path: str, spreadsheet_id: str) -> gspread.Worksheet:
    return open_spreadsheet(credentials_path, spreadsheet_id).sheet1


def list_tasks(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()


def add_task(ws: gspread.Worksheet, title: str, content: str, due: str) -> str:
    rid = str(uuid.uuid4())
    ws.append_row([rid, title, content, due, ""], value_input_option="USER_ENTERED")
    return rid


def _row_index_for_id(ws: gspread.Worksheet, task_id: str) -> int | None:
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row and row[0] == task_id:
            return i
    return None


def _pad_row(values: list, width: int) -> list[str]:
    out = [str(v) if v is not None else "" for v in values]
    while len(out) < width:
        out.append("")
    return out[:width]


def update_task(ws: gspread.Worksheet, task_id: str, title: str, content: str, due: str) -> bool:
    r = _row_index_for_id(ws, task_id)
    if r is None:
        return False
    row_vals = _pad_row(ws.row_values(r), 5)
    # ステータス列は維持（未設定なら空）
    ws.update(
        range_name=f"A{r}:E{r}",
        values=[[task_id, title, content, due, row_vals[4]]],
        value_input_option="USER_ENTERED",
    )
    return True


def mark_task_completed(ws: gspread.Worksheet, task_id: str) -> bool:
    r = _row_index_for_id(ws, task_id)
    if r is None:
        return False
    row_vals = _pad_row(ws.row_values(r), 5)
    row_vals[4] = STATUS_DONE
    ws.update(range_name=f"A{r}:E{r}", values=[row_vals], value_input_option="USER_ENTERED")
    return True


def delete_task(ws: gspread.Worksheet, task_id: str) -> bool:
    r = _row_index_for_id(ws, task_id)
    if r is None:
        return False
    ws.delete_rows(r)
    return True


def main_sheet_has_status_column(ws: gspread.Worksheet) -> bool:
    header = ws.row_values(1)
    return "ステータス" in header


def get_or_create_archive_sheet(sh: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        archive = sh.worksheet("Archive")
    except gspread.WorksheetNotFound:
        archive = sh.add_worksheet(title="Archive", rows=2000, cols=10)
    main_header = sh.sheet1.row_values(1)
    arch_values = archive.get_all_values()
    if not arch_values or not any((str(c).strip() for c in arch_values[0])):
        if main_header:
            archive.append_row(_pad_row(main_header, len(main_header)), value_input_option="USER_ENTERED")
    return archive


def archive_completed_tasks(sh: gspread.Spreadsheet) -> tuple[int, str]:
    main = sh.sheet1
    if not main_sheet_has_status_column(main):
        return 0, "メインシートの1行目に「ステータス」列がありません。"

    header = main.row_values(1)
    try:
        status_idx = header.index("ステータス")
    except ValueError:
        return 0, "「ステータス」列が見つかりません。"

    all_rows = main.get_all_values()
    if len(all_rows) < 2:
        return 0, "アーカイブ対象の行がありません。"

    width = len(header)
    to_move: list[list[str]] = []
    delete_row_nums: list[int] = []

    for i, row in enumerate(all_rows[1:], start=2):
        padded = _pad_row(row, width)
        if padded[status_idx].strip() == STATUS_DONE:
            to_move.append(padded)
            delete_row_nums.append(i)

    if not to_move:
        return 0, "完了済みタスクはありません。"

    archive = get_or_create_archive_sheet(sh)
    archive.append_rows(to_move, value_input_option="USER_ENTERED")

    for r in sorted(delete_row_nums, reverse=True):
        main.delete_rows(r)

    return len(to_move), "OK"
