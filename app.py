from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import requests
import streamlit as st

from src import todo_sheets


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _load_settings() -> tuple[str, str | None, bool]:
    """(spreadsheet_id, credentials_path or None, use_inline_service_account_from_secrets)"""
    root = _project_root()
    try:
        if "spreadsheet_id" not in st.secrets:
            raise KeyError
        sid = str(st.secrets["spreadsheet_id"]).strip()
        if "gcp_service_account" in st.secrets:
            return sid, None, True
        cred_rel = str(st.secrets.get("credentials_path", "secrets/service_account.json"))
        return sid, str((root / cred_rel).resolve()), False
    except Exception:
        pass
    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not cred:
        cred = str((root / "secrets" / "service_account.json").resolve())
    else:
        cred = str(Path(cred).resolve())
    return sid, cred, False


@st.cache_resource
def _spreadsheet(spreadsheet_id: str, credentials_path: str | None, use_inline_sa: bool):
    if use_inline_sa:
        info = {k: v for k, v in st.secrets["gcp_service_account"].items()}
        return todo_sheets.open_spreadsheet_from_service_account_info(info, spreadsheet_id)
    assert credentials_path is not None
    return todo_sheets.open_spreadsheet(credentials_path, spreadsheet_id)


def _task_sort_key(row: dict) -> tuple[date, str]:
    due_raw = str(row.get("期日", "")).strip()
    try:
        due = date.fromisoformat(due_raw)
    except ValueError:
        due = date.max
    title = str(row.get("タイトル", ""))
    return due, title


def _due_status(due_raw: str) -> tuple[str, str]:
    due_text = due_raw.strip()
    try:
        due_day = date.fromisoformat(due_text)
    except ValueError:
        return "期日未設定", "status-neutral"
    today = date.today()
    if due_day < today:
        return "期限切れ", "status-overdue"
    if due_day == today:
        return "今日まで", "status-today"
    return "余裕あり", "status-upcoming"


def _is_active_task(row: dict) -> bool:
    return str(row.get("ステータス", "")).strip() != todo_sheets.STATUS_DONE


def _parse_due_date(due_raw: str) -> date | None:
    due_text = str(due_raw).strip()
    try:
        return date.fromisoformat(due_text)
    except ValueError:
        return None


def _build_line_message(tasks: list[dict]) -> str:
    lines = ["【Todo通知】今日が期日の未完了タスク"]
    for t in tasks:
        title = str(t.get("タイトル", "")).strip()
        if title:
            lines.append(f"・{title}")
    return "\n".join(lines)


def _send_line_broadcast(text: str) -> None:
    if "line_messaging" not in st.secrets:
        raise KeyError("line_messaging が Secrets に設定されていません。")
    lm = st.secrets["line_messaging"]
    token = str(lm.get("channel_access_token", "")).strip()
    if not token:
        raise KeyError("line_messaging.channel_access_token が空です。")
    mode = str(lm.get("mode", "broadcast")).strip().lower()
    if mode != "broadcast":
        raise ValueError("現状は mode = \"broadcast\" のみ対応しています。")

    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "messages": [{"type": "text", "text": text}],
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


def main() -> None:
    st.set_page_config(page_title="やることリスト", layout="centered")
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 760px;
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
        }
        .app-caption {
            margin-top: -0.2rem;
            margin-bottom: 1rem;
            color: #6b7280;
            font-size: 0.95rem;
        }
        .section-card {
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 1rem 1rem 0.5rem 1rem;
            background: #ffffff;
        }
        div.stButton > button {
            min-height: 2.8rem;
            border-radius: 10px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        div.stButton > button[kind="primary"] {
            background: #111827;
            border: 1px solid #111827;
            color: #ffffff;
        }
        div.stButton > button[kind="primary"]:hover {
            background: #000000;
            border-color: #000000;
        }
        div[data-testid="stExpander"] {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 0.6rem;
        }
        .quick-count {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 0.8rem 1rem;
            margin: 0.5rem 0 1rem 0;
            background: #fafafa;
            font-size: 0.95rem;
        }
        .status-badge {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        .status-overdue {
            background: #fee2e2;
            color: #991b1b;
        }
        .status-today {
            background: #ffedd5;
            color: #9a3412;
        }
        .status-upcoming {
            background: #dcfce7;
            color: #166534;
        }
        .status-neutral {
            background: #e5e7eb;
            color: #374151;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    spreadsheet_id, credentials_path, use_inline_sa = _load_settings()
    if not spreadsheet_id:
        st.error("スプレッドシート ID が未設定です。")
        st.info(
            "`.streamlit/secrets.toml` を作成し、`spreadsheet_id` を設定してください。"
            " ひな形: `.streamlit/secrets.example.toml` をコピーして `secrets.toml` にリネームします。"
        )
        st.stop()

    try:
        sh = _spreadsheet(spreadsheet_id, credentials_path, use_inline_sa)
        ws = sh.sheet1
    except Exception as e:
        st.error("スプレッドシートに接続できませんでした。")
        st.caption(str(e))
        st.info(
            "サービスアカウントのメールをスプレッドシートの「共有」に **編集者** で追加したか、"
            "`secrets/service_account.json` のパスが正しいか確認してください。"
        )
        st.stop()

    if not todo_sheets.main_sheet_has_status_column(ws):
        st.error("スプレッドシートの1行目に「ステータス」列がありません。")
        st.info(
            "先頭シートの **1行目** を次の列名にしてください（E列に追加）: "
            "`id` / `タイトル` / `内容` / `期日` / **`ステータス`**。"
            " 既存データの「ステータス」は空欄で問題ありません。"
        )
        st.stop()

    st.title("やることリスト")
    st.markdown('<p class="app-caption">入力は上、確認は下。迷わない1画面です。</p>', unsafe_allow_html=True)

    # --- LINE通知（起動時に1日1回だけ送るガード） ---
    today = date.today()
    all_records_for_notify = todo_sheets.list_tasks(ws)
    due_today_pending = [
        r
        for r in all_records_for_notify
        if _parse_due_date(r.get("期日", "")) == today
        and str(r.get("ステータス", "")).strip() != todo_sheets.STATUS_DONE
    ]

    # Streamlit は再実行されるため、セッション内で「今日は送ったか」を覚えて二重送信を防ぐ
    sent_key = f"line_sent_{today.isoformat()}"
    if sent_key not in st.session_state and due_today_pending:
        try:
            msg = _build_line_message(due_today_pending)
            _send_line_broadcast(msg)
            st.session_state[sent_key] = True
            st.success("LINEに通知を送りました（今日が期日のタスク）。")
        except Exception as e:
            st.info(f"LINE通知は未設定または失敗しました: {str(e)}")
    elif not due_today_pending:
        # 送るものがないときは静かに（必要なら st.caption でもOK）
        pass

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("1. 新しいタスクを追加")
    with st.form("add_task_form", clear_on_submit=True):
        t_title = st.text_input("タイトル", placeholder="例: 資料を送る")
        t_body = st.text_area("内容", placeholder="詳細があれば入力", height=100)
        t_due = st.date_input("期日")
        submitted = st.form_submit_button("追加する", type="primary", use_container_width=True)
    if submitted:
        if not t_title.strip():
            st.warning("タイトルを入力してください。")
        else:
            todo_sheets.add_task(ws, t_title.strip(), t_body.strip(), t_due.isoformat())
            _spreadsheet.clear()
            st.success("追加しました。")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("2. いまのタスクを確認・編集")

    all_records = todo_sheets.list_tasks(ws)
    active_tasks = sorted([r for r in all_records if _is_active_task(r)], key=_task_sort_key)
    done_count = len(all_records) - len(active_tasks)

    st.markdown(
        f'<div class="quick-count">未完了: <b>{len(active_tasks)}</b> 件'
        f'　·　完了（まだシート上に残っている）: <b>{done_count}</b> 件</div>',
        unsafe_allow_html=True,
    )

    if st.button("完了済みタスクをアーカイブする", use_container_width=True, key="bulk_archive"):
        moved, msg = todo_sheets.archive_completed_tasks(sh)
        _spreadsheet.clear()
        if moved:
            st.success(f"{moved} 件を「Archive」シートへ移し、メインシートから削除しました。")
        else:
            st.info(msg)
        st.rerun()

    if not active_tasks:
        st.caption("表示できる未完了タスクはありません。上のフォームから追加するか、完了済みはアーカイブしてください。")
        return

    st.divider()
    st.subheader("LINE通知（テスト／手動送信）")
    due_today_pending = sorted(due_today_pending, key=lambda r: str(r.get("タイトル", "")))
    line_test_text = _build_line_message(due_today_pending) if due_today_pending else "【Todo通知】今日が期日の未完了タスクはありません"
    if st.button("今日が期日のタスクをLINEに通知する", use_container_width=True):
        try:
            _send_line_broadcast(line_test_text)
            st.success("LINEに通知を送りました。")
        except Exception as e:
            st.error(f"LINE通知に失敗しました: {str(e)}")

    for row in active_tasks:
        tid = str(row.get("id", "")).strip()
        title = str(row.get("タイトル", ""))
        due_raw = str(row.get("期日", ""))
        status_text, status_class = _due_status(due_raw)
        prefix = "🟥" if status_text == "期限切れ" else "🟧" if status_text == "今日まで" else "🟩"
        label = f"{prefix} {title}" if title else f"{prefix} (無題)"

        col_done, col_body = st.columns([1, 6])
        with col_done:
            if tid and st.button("✅", key=f"done_{tid}", help="完了にする", use_container_width=True):
                if todo_sheets.mark_task_completed(ws, tid):
                    _spreadsheet.clear()
                    st.rerun()
        with col_body:
            with st.expander(label):
                if not tid:
                    st.warning("この行に id がありません。シートの見出し行を確認してください。")
                    continue
                st.markdown(
                    f'<span class="status-badge {status_class}">{status_text}</span>',
                    unsafe_allow_html=True,
                )
                nt = st.text_input("タイトル", value=title, key=f"title_{tid}")
                nc = st.text_area(
                    "内容",
                    value=str(row.get("内容", "")),
                    height=80,
                    key=f"body_{tid}",
                )
                nd = st.text_input("期日（YYYY-MM-DD）", value=due_raw, key=f"due_{tid}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("保存する", type="primary", use_container_width=True, key=f"save_{tid}"):
                        if todo_sheets.update_task(ws, tid, nt.strip(), nc.strip(), nd.strip()):
                            _spreadsheet.clear()
                            st.success("保存しました。")
                            st.rerun()
                        else:
                            st.error("保存に失敗しました。")
                with c2:
                    if st.button("削除する", use_container_width=True, key=f"del_{tid}"):
                        if todo_sheets.delete_task(ws, tid):
                            _spreadsheet.clear()
                            st.success("削除しました。")
                            st.rerun()
                        else:
                            st.error("削除に失敗しました。")


if __name__ == "__main__":
    main()
