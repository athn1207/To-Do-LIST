from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st

from src import todo_sheets


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _load_settings() -> tuple[str, str]:
    root = _project_root()
    try:
        if "spreadsheet_id" not in st.secrets:
            raise KeyError
        sid = str(st.secrets["spreadsheet_id"]).strip()
        cred_rel = str(st.secrets.get("credentials_path", "secrets/service_account.json"))
        return sid, str((root / cred_rel).resolve())
    except Exception:
        pass
    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not cred:
        cred = str((root / "secrets" / "service_account.json").resolve())
    else:
        cred = str(Path(cred).resolve())
    return sid, cred


@st.cache_resource
def _worksheet(credentials_path: str, spreadsheet_id: str):
    return todo_sheets.open_first_worksheet(credentials_path, spreadsheet_id)


def _task_sort_key(row: dict) -> tuple[date, str]:
    due_raw = str(row.get("期日", "")).strip()
    try:
        due = date.fromisoformat(due_raw)
    except ValueError:
        # 期日が空欄/不正な場合は末尾表示にする
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

    spreadsheet_id, credentials_path = _load_settings()
    if not spreadsheet_id:
        st.error("スプレッドシート ID が未設定です。")
        st.info(
            "`.streamlit/secrets.toml` を作成し、`spreadsheet_id` を設定してください。"
            " ひな形: `.streamlit/secrets.example.toml` をコピーして `secrets.toml` にリネームします。"
        )
        st.stop()

    try:
        ws = _worksheet(credentials_path, spreadsheet_id)
    except Exception as e:
        st.error("スプレッドシートに接続できませんでした。")
        st.caption(str(e))
        st.info(
            "サービスアカウントのメールをスプレッドシートの「共有」に **編集者** で追加したか、"
            "`secrets/service_account.json` のパスが正しいか確認してください。"
        )
        st.stop()

    st.title("やることリスト")
    st.markdown('<p class="app-caption">入力は上、確認は下。迷わない1画面です。</p>', unsafe_allow_html=True)

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
            _worksheet.clear()
            st.success("追加しました。")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("2. いまのタスクを確認・編集")

    tasks = sorted(todo_sheets.list_tasks(ws), key=_task_sort_key)
    st.markdown(f'<div class="quick-count">登録タスク数: <b>{len(tasks)}</b> 件</div>', unsafe_allow_html=True)
    if not tasks:
        st.caption("まだタスクがありません。上のフォームから追加してください。")
        return

    for row in tasks:
        tid = str(row.get("id", "")).strip()
        title = str(row.get("タイトル", ""))
        due_raw = str(row.get("期日", ""))
        status_text, status_class = _due_status(due_raw)
        prefix = "🟥" if status_text == "期限切れ" else "🟧" if status_text == "今日まで" else "🟩"
        label = f"{prefix} {title}" if title else f"{prefix} (無題)"
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
                        _worksheet.clear()
                        st.success("保存しました。")
                        st.rerun()
                    else:
                        st.error("保存に失敗しました。")
            with c2:
                if st.button("削除する", use_container_width=True, key=f"del_{tid}"):
                    if todo_sheets.delete_task(ws, tid):
                        _worksheet.clear()
                        st.success("削除しました。")
                        st.rerun()
                    else:
                        st.error("削除に失敗しました。")


if __name__ == "__main__":
    main()
