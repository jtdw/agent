from __future__ import annotations

from html import escape
from pathlib import Path
import json
import os

import streamlit as st
import streamlit.components.v1 as components

from core.service import GISWorkspaceService
from core.commercial.service import CommercialService, PLAN_PRESETS


st.set_page_config(
    page_title="GIS智能体",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """

    <style>
    :root {
        --bg-main: #f6f8fb;
        --bg-soft: #f8fafc;
        --surface: #ffffff;
        --surface-strong: #ffffff;
        --panel: #ffffff;
        --line: #e2e8f0;
        --line-strong: #bfdbfe;
        --text-main: #0f172a;
        --text-sub: #64748b;
        --text-faint: #94a3b8;
        --blue: #2563eb;
        --blue-dark: #1d4ed8;
        --violet: #7c3aed;
        --mint: #059669;
        --amber: #d97706;
        --rose: #dc2626;
        --shadow-sm: 0 8px 22px rgba(15, 23, 42, 0.06);
        --shadow-md: 0 18px 45px rgba(15, 23, 42, 0.08);
    }

    .stApp {
        background:
            radial-gradient(circle at 10% 4%, rgba(37, 99, 235, 0.08), transparent 25%),
            radial-gradient(circle at 88% 2%, rgba(124, 58, 237, 0.07), transparent 28%),
            linear-gradient(180deg, #ffffff 0%, #f6f8fb 50%, #eef4fb 100%);
        color: var(--text-main);
    }

    .block-container {
        max-width: 1920px;
        padding-top: 0.35rem;
        padding-bottom: 0.95rem;
        padding-left: 1rem;
        padding-right: 1rem;
        overflow-x: clip;
    }

    .stApp,
    div[data-testid="stAppViewContainer"],
    section[data-testid="stSidebar"],
    div[data-testid="stMainBlockContainer"] {
        overflow-x: clip !important;
    }

    div[data-testid="column"],
    div[data-testid="stVerticalBlock"],
    div[data-testid="stHorizontalBlock"] {
        min-width: 0;
        max-width: 100%;
    }

    div[data-testid="column"]:has(.main-center-anchor) {
        flex: 1 1 0% !important;
        min-width: 0 !important;
        max-width: calc(100% - 320px) !important;
        overflow: hidden !important;
    }

    div[data-testid="column"]:has(.main-right-anchor) {
        flex: 0 1 clamp(300px, 22vw, 360px) !important;
        width: clamp(300px, 22vw, 360px) !important;
        min-width: 300px !important;
        max-width: 360px !important;
        overflow: hidden !important;
    }

    div[data-testid="stSidebar"] {
        min-width: 250px !important;
        max-width: 280px !important;
        width: 264px !important;
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        border-right: 1px solid var(--line);
        box-shadow: 18px 0 42px rgba(15, 23, 42, 0.06);
    }

    div[data-testid="stSidebar"] * {
        color: var(--text-main);
    }

    .sidebar-brand,
    .sidebar-card,
    .dock-card,
    .mini-stat,
    .empty-card,
    .artifact-card,
    .dataset-card,
    .meta-card,
    .activity-card,
    .chat-hero {
        border: 1px solid var(--line);
        background: var(--surface);
        box-shadow: var(--shadow-sm);
    }

    .sidebar-brand {
        border-radius: 24px;
        padding: 1.08rem 1.12rem;
        margin-bottom: 0.95rem;
        background: linear-gradient(135deg, #ffffff 0%, #f1f7ff 58%, #eef2ff 100%);
        border-color: #dbeafe;
    }

    .sidebar-card,
    .dock-card,
    .activity-card,
    .chat-hero {
        border-radius: 22px;
        padding: 0.95rem 1rem;
        margin-bottom: 0.78rem;
    }

    .mini-stat {
        border-radius: 20px;
        padding: 0.9rem 0.95rem;
        min-height: 108px;
        margin-bottom: 0.68rem;
        background: linear-gradient(150deg, #ffffff 0%, #f8fafc 60%, #eff6ff 100%);
    }

    .artifact-card,
    .dataset-card,
    .empty-card,
    .meta-card {
        border-radius: 18px;
        padding: 0.82rem 0.9rem;
        margin-bottom: 0.7rem;
    }

    .chat-hero {
        background: linear-gradient(145deg, #ffffff 0%, #f1f7ff 52%, #eef2ff 100%);
        border: 1px solid #dbeafe;
        padding: 1rem 1.08rem;
    }

    .hero-title,
    .sidebar-title,
    .section-title,
    .stat-value,
    .topbar-title,
    .topbar-kpi-value,
    .result-hero-title,
    .artifact-title,
    .dataset-title {
        color: var(--text-main);
    }

    .hero-title {
        font-size: 1.18rem;
        font-weight: 900;
        letter-spacing: -0.02em;
        margin-bottom: 0.24rem;
    }

    .hero-sub,
    .sidebar-sub,
    .muted,
    .caption-line,
    .topbar-sub,
    .topbar-kpi-note,
    .result-hero-sub {
        color: var(--text-sub);
        line-height: 1.58;
    }

    .sidebar-title {
        font-size: 1.36rem;
        font-weight: 900;
        margin-bottom: 0.18rem;
        letter-spacing: -0.01em;
    }

    .sidebar-sub,
    .muted,
    .caption-line { font-size: 0.9rem; }

    .section-title {
        font-size: 0.95rem;
        font-weight: 900;
        margin-bottom: 0.58rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .stat-label {
        font-size: 0.83rem;
        color: var(--text-sub);
        margin-bottom: 0.22rem;
    }

    .stat-value {
        font-size: 1.78rem;
        font-weight: 900;
        line-height: 1.05;
        margin-bottom: 0.16rem;
    }

    .accent-blue { color: var(--blue); }
    .accent-violet { color: var(--violet); }
    .accent-mint { color: var(--mint); }

    .badge-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.74rem;
    }

    .badge,
    .hint-chip,
    .product-pill {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        font-size: 0.8rem;
        border: 1px solid #dbeafe;
        background: #eff6ff;
        color: #1e3a8a;
    }

    .badge { padding: 0.32rem 0.7rem; }
    .hint-chip { display:inline-block; margin-right:0.42rem; margin-bottom:0.44rem; padding:0.32rem 0.72rem; }
    .product-pill { gap:0.36rem; padding:0.38rem 0.78rem; }

    div[data-testid="column"] > div[data-testid="stVerticalBlock"]:has(.chat-root-anchor) { height: 100%; }
    .chat-root-anchor, .main-center-anchor, .main-right-anchor, .msg-user-anchor, .msg-assistant-anchor, .msg-system-anchor { display: none; }

    .stImage, .stCodeBlock, pre, code, iframe, canvas, svg, img, table { max-width: 100% !important; }
    div[data-testid="stImage"] img {
        display: block;
        max-width: 100% !important;
        width: 100% !important;
        height: auto !important;
        object-fit: contain;
        border-radius: 16px;
        border: 1px solid var(--line);
        box-shadow: var(--shadow-sm);
    }

    div[data-testid="stChatMessage"] {
        background: transparent;
        border: none;
        padding: 0;
        box-shadow: none;
        margin-bottom: 0.78rem;
    }

    div[data-testid="stChatMessage"]:has(.msg-user-anchor) {
        margin-left: 6%;
        background: linear-gradient(135deg, #eff6ff 0%, #ffffff 74%);
        border: 1px solid #bfdbfe;
        border-radius: 24px;
        padding: 0.55rem 1rem 0.72rem 1rem;
        box-shadow: var(--shadow-md);
    }

    div[data-testid="stChatMessage"]:has(.msg-assistant-anchor) {
        margin-right: 2%;
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 24px;
        padding: 0.55rem 1rem 0.72rem 1rem;
        box-shadow: var(--shadow-md);
    }

    div[data-testid="stChatMessage"]:has(.msg-system-anchor) {
        background: #fff7ed;
        border: 1px solid #fed7aa;
        border-radius: 22px;
        padding: 0.5rem 0.95rem 0.68rem 0.95rem;
    }

    .msg-role-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.42rem;
        padding: 0.28rem 0.68rem;
        border-radius: 999px;
        font-size: 0.77rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        margin-bottom: 0.28rem;
        text-transform: uppercase;
    }

    .user-pill { background:#dbeafe; border:1px solid #bfdbfe; color:#1d4ed8; }
    .assistant-pill { background:#f1f5f9; border:1px solid var(--line); color:#475569; }
    .system-pill { background:#ffedd5; border:1px solid #fed7aa; color:#9a3412; }

    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] { width: 100%; }
    div[data-testid="stChatMessage"] p,
    div[data-testid="stChatMessage"] li,
    div[data-testid="stChatMessage"] span { font-size: 1rem; line-height: 1.75; color: var(--text-main); }
    div[data-testid="stChatMessageContent"] { width: 100%; max-width: none; }

    .copy-wrap { display:flex; justify-content:flex-end; margin:0.05rem 0 0.18rem 0; }

    .meta-card {
        background: #f8fafc;
        border: 1px solid var(--line);
    }

    .dock-root { width:100%; max-width:100%; min-width:0; margin-left:auto; overflow:hidden; }
    .dock-root *, .dock-card *, .artifact-card *, .dataset-card *, .meta-card *, .activity-card *, .mini-stat *, .stTabs *, .stCodeBlock *, code, pre {
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.35rem;
        background: #f1f5f9;
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 0.34rem;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 12px;
        min-height: 40px;
        color: var(--text-sub);
        font-weight: 800;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, var(--blue), var(--violet)) !important;
        color: #ffffff !important;
        box-shadow: 0 12px 28px rgba(37, 99, 235, 0.18);
    }

    button[kind="primary"], button[kind="secondary"], button[kind="tertiary"] {
        border-radius: 14px !important;
        transition: all 0.18s ease;
        font-weight: 800 !important;
        letter-spacing: 0.01em;
    }

    button[kind="primary"] {
        background: linear-gradient(90deg, var(--blue) 0%, var(--violet) 100%) !important;
        color: #ffffff !important;
        border: 1px solid #bfdbfe !important;
        box-shadow: 0 14px 30px rgba(37, 99, 235, 0.18);
    }
    button[kind="primary"]:hover { transform: translateY(-1px); box-shadow:0 16px 34px rgba(37,99,235,0.22); }

    button[kind="secondary"] {
        background: #ffffff !important;
        color: #334155 !important;
        border: 1px solid var(--line) !important;
        box-shadow: var(--shadow-sm);
    }
    button[kind="secondary"]:hover { border-color:#cbd5e1 !important; background:#f8fafc !important; }

    button[kind="tertiary"] {
        background: #f1f5f9 !important;
        color: #334155 !important;
        border: 1px solid var(--line) !important;
    }

    .stDownloadButton button {
        background: linear-gradient(90deg, var(--mint), #10b981) !important;
        color: #ffffff !important;
        border: 1px solid #bbf7d0 !important;
        border-radius: 14px !important;
        box-shadow: 0 12px 26px rgba(5, 150, 105, 0.18);
        font-weight: 800 !important;
    }

    textarea, input, div[data-baseweb="select"] > div, div[data-testid="stChatInput"] textarea { border-radius: 14px !important; }
    textarea, input, div[data-baseweb="select"] > div {
        background: #ffffff !important;
        color: var(--text-main) !important;
        border-color: var(--line) !important;
    }

    div[data-testid="stChatInput"] {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 0.4rem 0.55rem 0.2rem 0.55rem;
        box-shadow: var(--shadow-md);
    }
    div[data-testid="stChatInput"] textarea { background: transparent !important; color: var(--text-main) !important; }

    div[data-testid="stFileUploader"] section {
        border-radius: 18px !important;
        border: 1px dashed #bfdbfe !important;
        background: #f8fafc;
    }

    .app-topbar {
        border: 1px solid var(--line);
        background: linear-gradient(180deg, #ffffff, #f8fafc);
        border-radius: 22px;
        padding: 0.95rem 1.05rem;
        margin-bottom: 0.85rem;
        box-shadow: var(--shadow-md);
    }

    .topbar-grid { display:grid; grid-template-columns:minmax(220px,1.35fr) repeat(5,minmax(112px,1fr)); gap:0.8rem; align-items:stretch; }
    .topbar-main { padding-right:0.6rem; border-right:1px solid var(--line); }
    .topbar-title { font-size:1.12rem; font-weight:900; letter-spacing:-0.02em; margin-bottom:0.18rem; }
    .topbar-sub { font-size:0.88rem; }
    .topbar-kpi { border-radius:16px; padding:0.78rem 0.82rem; border:1px solid var(--line); background:#ffffff; }
    .topbar-kpi-label { font-size:0.74rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-faint); margin-bottom:0.18rem; }
    .topbar-kpi-value { font-size:1.05rem; font-weight:850; line-height:1.2; }
    .topbar-kpi-note { font-size:0.8rem; margin-top:0.18rem; }

    @media (max-width: 1280px) {
        .topbar-grid { grid-template-columns: 1fr 1fr 1fr; }
        .topbar-main { border-right: none; }
    }

    .product-strip { display:flex; flex-wrap:wrap; gap:0.5rem; margin:0.18rem 0 0.84rem 0; }
    .account-status-card {
        border-radius: 20px;
        border: 1px solid #dbeafe;
        background: linear-gradient(145deg, #ffffff 0%, #f8fbff 65%, #eef6ff 100%);
        box-shadow: var(--shadow-sm);
        padding: 0.92rem 0.95rem;
        margin: 0.55rem 0 0.75rem 0;
    }
    .account-name { font-size:0.98rem; font-weight:900; color:var(--text-main); margin-bottom:0.18rem; }
    .account-meta { font-size:0.82rem; color:var(--text-sub); line-height:1.55; }
    .account-badge {
        display:inline-flex; align-items:center; border-radius:999px;
        padding:0.26rem 0.62rem; font-size:0.76rem; font-weight:850;
        border:1px solid #bfdbfe; background:#eff6ff; color:#1d4ed8;
        margin-right:0.34rem; margin-top:0.45rem;
    }
    .account-badge.member { border-color:#c4b5fd; background:#f5f3ff; color:#6d28d9; }
    .account-badge.free { border-color:#cbd5e1; background:#f8fafc; color:#475569; }
    .account-badge.quota { border-color:#bbf7d0; background:#ecfdf5; color:#047857; }
    .locked-secret-note {
        border-radius:16px; border:1px dashed #bfdbfe; background:#f8fafc;
        color:var(--text-sub); padding:0.72rem 0.78rem; font-size:0.84rem; line-height:1.58;
        margin:0.5rem 0;
    }
    .input-toolbar {
        border: 1px solid var(--line);
        background: #ffffff;
        border-radius: 18px;
        padding: 0.8rem 0.9rem;
        margin: 0.75rem 0 0.55rem 0;
        box-shadow: var(--shadow-sm);
    }
    .toolbar-title { font-size:0.82rem; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-sub); margin-bottom:0.55rem; font-weight:800; }

    .result-hero {
        border-radius: 18px;
        padding: 0.82rem 0.9rem;
        margin-bottom: 0.7rem;
        border: 1px solid #dbeafe;
        background: linear-gradient(180deg, #ffffff, #f1f7ff);
    }
    .result-hero-title { font-size:0.9rem; font-weight:800; margin-bottom:0.18rem; }
    .result-hero-sub { font-size:0.83rem; }
    .gallery-thumb { border-radius:14px; overflow:hidden; border:1px solid var(--line); }

    /* Make native Streamlit text elements consistent with the white theme. */
    .stMarkdown, .stCaption, .stText, label, p, li { color: var(--text-main); }
    .stCaption, small { color: var(--text-sub) !important; }
    hr { border-color: var(--line) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_copy_button(label: str, text: str, key: str) -> None:
    payload = json.dumps(text, ensure_ascii=False)
    button_id = f"copy_btn_{key}"
    components.html(
        f"""
        <div class="copy-wrap">
          <button id="{button_id}" style="background:linear-gradient(90deg,#2563eb,#7c3aed);color:#fff;border:none;border-radius:999px;padding:0.32rem 0.82rem;font-size:0.8rem;font-weight:700;cursor:pointer;box-shadow:0 10px 24px rgba(37,99,235,0.18);">{escape(label)}</button>
        </div>
        <script>
          const btn = document.getElementById({json.dumps(button_id)});
          if (btn) {{
            btn.addEventListener('click', async () => {{
              try {{
                await navigator.clipboard.writeText({payload});
                btn.innerText = '已复制';
                setTimeout(() => btn.innerText = {json.dumps(label)}, 1200);
              }} catch (err) {{
                btn.innerText = '复制失败';
                setTimeout(() => btn.innerText = {json.dumps(label)}, 1500);
              }}
            }});
          }}
        </script>
        """,
        height=36,
    )


def format_conversation_text(messages: list[dict]) -> str:
    blocks: list[str] = []
    for item in messages:
        role = item.get("role", "system")
        role_text = {"user": "用户", "assistant": "智能体", "system": "系统"}.get(role, role)
        content = item.get("content", "")
        blocks.append(f"{role_text}:\n{content}")
    return "\n\n".join(blocks).strip()


def latest_assistant_text(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "assistant" and item.get("content"):
            return item["content"]
    return ""


def session_display_labels(sessions: list[dict]) -> dict[str, str]:
    counts: dict[str, int] = {}
    for item in sessions:
        title = (item.get("title") or "新对话").strip() or "新对话"
        counts[title] = counts.get(title, 0) + 1

    labels: dict[str, str] = {}
    for item in sessions:
        title = (item.get("title") or "新对话").strip() or "新对话"
        if counts.get(title, 0) > 1:
            stamp = (item.get("updated_at") or item.get("created_at") or "")[:16].replace("T", " ")
            labels[item["session_id"]] = f"{title}（{stamp}）" if stamp else title
        else:
            labels[item["session_id"]] = title
    return labels


def current_session_title(dashboard: dict) -> str:
    current = dashboard.get("current_session_id")
    labels = session_display_labels(dashboard.get("sessions", []))
    return labels.get(current, "当前会话")


PLAN_LABELS = {
    "free": "普通用户",
    "basic": "基础会员",
    "pro": "PRO 会员",
    "team": "团队会员",
}

PLAN_PRICES = {
    "basic": 900,
    "pro": 2000,
    "team": 6990,
}


def plan_label(plan: str) -> str:
    return PLAN_LABELS.get(str(plan or "free").lower(), str(plan or "free"))


def plan_account_type(plan: str) -> str:
    return "普通用户" if str(plan or "free").lower() == "free" else "会员用户"


def money_yuan(cents: int | str | None) -> str:
    try:
        return f"¥{int(cents or 0) / 100:.2f}"
    except Exception:
        return "¥0.00"


def _refresh_commercial_user_from_db() -> dict | None:
    user = st.session_state.get("commercial_user")
    if not user:
        sid = st.session_state.get("commercial_session_id") or ""
        token = st.session_state.get("commercial_session_token") or ""
        if sid and token:
            try:
                payload = commercial.validate_session(sid, token)
                st.session_state.commercial_user = payload["user"]
                user = payload["user"]
            except Exception:
                st.session_state.commercial_user = None
                st.session_state.commercial_session_id = ""
                st.session_state.commercial_session_token = ""
                return None
        else:
            return None
    try:
        summary = commercial.permission_summary(user["user_id"])
        st.session_state.commercial_user = summary["user"]
        return summary
    except Exception:
        st.session_state.commercial_user = None
        st.session_state.commercial_session_id = ""
        st.session_state.commercial_session_token = ""
        return None


def get_commercial_summary() -> dict | None:
    return _refresh_commercial_user_from_db()


def seed_platform_account_from_env() -> None:
    """Load backend GSCloud account from environment once, without exposing it in UI."""
    if st.session_state.get("platform_env_seed_checked"):
        return
    st.session_state.platform_env_seed_checked = True
    username = os.getenv("GSCLOUD_PLATFORM_USERNAME", "").strip()
    password = os.getenv("GSCLOUD_PLATFORM_PASSWORD", "").strip()
    state_path = os.getenv("GSCLOUD_PLATFORM_STORAGE_STATE", "").strip()
    label = os.getenv("GSCLOUD_PLATFORM_LABEL", "后台地理空间数据云账号").strip() or "后台地理空间数据云账号"
    if not username and not state_path:
        return
    try:
        commercial.upsert_platform_account(
            source_key="gscloud",
            username=username,
            password=password,
            label=label,
            daily_limit=int(os.getenv("GSCLOUD_PLATFORM_DAILY_LIMIT", "50") or 50),
            monthly_limit=int(os.getenv("GSCLOUD_PLATFORM_MONTHLY_LIMIT", "1000") or 1000),
            storage_state_path=state_path,
        )
    except Exception as exc:
        st.warning(f"后台平台账号自动载入失败：{exc}")



def render_login_register_forms() -> None:
    login_tab, register_tab = st.tabs(["登录", "注册"])
    with login_tab:
        with st.form("commercial_login_form", clear_on_submit=False):
            email = st.text_input("邮箱账号", key="commercial_login_email", placeholder="例如 user@example.com")
            password = st.text_input("登录密码", type="password", key="commercial_login_password")
            remember_days = st.selectbox("保持登录", options=[1, 7, 30], index=1, format_func=lambda x: f"{x} 天")
            submitted = st.form_submit_button("登录账号", use_container_width=True, type="primary")
        if submitted:
            try:
                payload = commercial.authenticate_user(email=email, password=password, remember_days=int(remember_days))
                st.session_state.commercial_user = payload["user"]
                st.session_state.commercial_session_id = payload["session_id"]
                st.session_state.commercial_session_token = payload["session_token"]
                st.session_state.show_commercial_login = False
                st.success("登录成功。")
                st.rerun()
            except Exception as exc:
                st.error(f"登录失败：{exc}")
    with register_tab:
        with st.form("commercial_register_form", clear_on_submit=False):
            email = st.text_input("注册邮箱", key="commercial_register_email", placeholder="例如 user@example.com")
            password = st.text_input("设置密码", type="password", key="commercial_register_password")
            password2 = st.text_input("确认密码", type="password", key="commercial_register_password2")
            submitted = st.form_submit_button("注册普通用户", use_container_width=True, type="primary")
        if submitted:
            if password != password2:
                st.error("两次输入的密码不一致。")
            else:
                try:
                    user = commercial.register_user(email=email, password=password, plan="free")
                    login_payload = commercial.authenticate_user(email=email, password=password, remember_days=7)
                    st.session_state.commercial_user = login_payload["user"]
                    st.session_state.commercial_session_id = login_payload["session_id"]
                    st.session_state.commercial_session_token = login_payload["session_token"]
                    st.session_state.show_commercial_login = False
                    st.success(f"注册成功，已以 {user.get('email')} 登录。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"注册失败：{exc}")


def render_account_status(summary: dict) -> None:
    user = summary.get("user", {})
    plan = str(user.get("plan") or "free").lower()
    remaining = int(summary.get("platform_quota_remaining") or 0)
    badge_class = "free" if plan == "free" else "member"
    st.markdown(
        f"""
        <div class='account-status-card'>
            <div class='account-name'>{escape(str(user.get('email') or user.get('user_id') or '-'))}</div>
            <div class='account-meta'>账号类型：{escape(plan_account_type(plan))} ｜ 套餐：{escape(plan_label(plan))}<br>
            到期时间：{escape(str(user.get('plan_expires_at') or '-'))}</div>
            <span class='account-badge {badge_class}'>{escape(plan_label(plan))}</span>
            <span class='account-badge quota'>平台额度剩余 {remaining}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_user_credential_panel(summary: dict) -> None:
    user = summary["user"]
    st.markdown("**普通用户自有数据源账号**")
    st.caption("普通用户可以保存自己的地理空间数据云账号；凭据加密进入同一套 commercial.db，桌面端和网页版共享。")
    with st.form("web_save_user_credential", clear_on_submit=False):
        source_key = st.selectbox("数据源", options=["gscloud"], format_func=lambda x: "地理空间数据云" if x == "gscloud" else x)
        username = st.text_input("数据源用户名", key="web_cred_username")
        password = st.text_input("数据源密码", type="password", key="web_cred_password")
        storage_state_path = st.text_input("Cookie / storage_state 路径（可选，服务器路径）", key="web_cred_state")
        submitted = st.form_submit_button("加密保存我的数据源账号", use_container_width=True, type="primary")
    if submitted:
        try:
            record = commercial.save_user_credential(
                user_id=user["user_id"],
                source_key=source_key,
                username=username,
                password=password,
                storage_state_path=storage_state_path,
            )
            st.success(f"已保存：{record.get('source_key')}，用户名掩码 {record.get('username_preview') or '-'}。")
        except Exception as exc:
            st.error(f"保存失败：{exc}")
    creds = commercial.list_user_credentials(user["user_id"])
    if creds:
        for cred in creds[:5]:
            st.caption(f"已保存：{cred.get('source_key')} ｜ {cred.get('credential_type')} ｜ 用户名 {cred.get('username_preview') or '-'} ｜ 密码 {'已保存' if cred.get('has_password') else '未保存'}")
    else:
        st.caption("还没有保存自有数据源账号。")


def render_payment_panel(summary: dict) -> None:
    user = summary["user"]
    st.markdown("**会员与模拟支付**")
    st.caption("当前为本地 MVP 的模拟支付：用于登记订单、更新套餐与平台账号下载额度，未接入真实支付网关。")
    with st.form("web_mock_payment_form", clear_on_submit=False):
        plan = st.selectbox("开通套餐", options=["basic", "pro", "team"], index=1, format_func=plan_label)
        preset = PLAN_PRESETS.get(plan, PLAN_PRESETS["pro"])
        amount_cents = st.number_input("金额（分）", min_value=0, value=int(PLAN_PRICES.get(plan, 2000)), step=100)
        quota = st.number_input("平台账号下载额度", min_value=0, value=int(preset.get("platform_monthly_quota", 50)), step=1)
        days = st.number_input("有效天数", min_value=1, value=int(preset.get("days", 30)), step=1)
        submitted = st.form_submit_button("模拟支付并开通会员", use_container_width=True, type="primary")
    if submitted:
        try:
            result = commercial.simulate_payment(user_id=user["user_id"], plan=plan, amount_cents=int(amount_cents), platform_quota=int(quota), days=int(days), note="Web 端模拟支付")
            st.session_state.commercial_user = result["user"]
            st.success(f"已开通 {plan_label(plan)}，金额 {money_yuan(amount_cents)}，平台额度 {int(quota)}。")
            st.rerun()
        except Exception as exc:
            st.error(f"支付登记失败：{exc}")
    records = commercial.list_payment_records(user["user_id"], limit=5)
    if records:
        st.caption("最近支付记录：")
        for item in records:
            st.caption(f"{item.get('created_at')} ｜ {plan_label(item.get('plan'))} ｜ {money_yuan(item.get('amount_cents'))} ｜ 额度 {item.get('platform_quota')}")


def render_platform_download_panel(summary: dict) -> None:
    user = summary["user"]
    remaining = int(summary.get("platform_quota_remaining") or 0)
    platform_accounts = commercial.status().get("active_platform_accounts", 0)
    st.markdown("**地理空间数据云下载模式**")
    st.markdown(
        f"<div class='locked-secret-note'>平台账号密码只保存在后台账号池。前台只选择“使用平台账号”，系统提交任务时会自动选取可用账号，不会把平台账号明文返回给用户。当前后台可用平台账号：{platform_accounts} 个。</div>",
        unsafe_allow_html=True,
    )
    mode_options = ["own"]
    if remaining > 0:
        mode_options.append("platform")
    account_mode = st.selectbox(
        "账号模式",
        options=mode_options,
        format_func=lambda x: "使用我的地理空间数据云账号（普通用户）" if x == "own" else "使用平台账号池（会员功能）",
        key="web_download_account_mode",
    )
    with st.form("web_gscloud_download_prompt_form", clear_on_submit=False):
        resource_type = st.selectbox("资源类型", options=["dem", "landsat", "sentinel", "other"], index=0, format_func=lambda x: {"dem":"DEM / ASTER GDEM", "landsat":"Landsat", "sentinel":"Sentinel", "other":"其他"}.get(x, x))
        region = st.text_input("区域", value="成都市", key="web_download_region")
        start_date = st.text_input("开始日期 / 年份（可选）", value="", key="web_download_start")
        end_date = st.text_input("结束日期（可选）", value="", key="web_download_end")
        request_text = st.text_area("补充说明", value="请自动完成分幅识别、分页扫描、下载和工作区入库。", height=90, key="web_download_request")
        submitted = st.form_submit_button("提交到智能体执行", use_container_width=True, type="primary")
    if submitted:
        if account_mode == "platform" and remaining <= 0:
            st.error("当前账号没有平台账号下载额度，请先开通会员。")
            return
        prompt = (
            "请使用商业化下载系统提交并执行地理空间数据云下载任务。\n"
            f"user_id={user['user_id']}\n"
            "source_key=gscloud\n"
            f"account_mode={account_mode}\n"
            f"resource_type={resource_type}\n"
            f"region={region}\n"
            f"start_date={start_date}\n"
            f"end_date={end_date}\n"
            f"request_text={request_text}\n"
            "要求：如果 account_mode=platform，则只调用后台平台账号池，不在前台显示或输出平台账号密码；如果 account_mode=own，则调用该用户已保存的自有账号或登录态。"
        )
        st.session_state.prefill = prompt
        st.success("已写入智能体任务队列，主对话区将开始执行。")
        st.rerun()
    jobs = commercial.list_jobs(user["user_id"], limit=5)
    if jobs:
        st.caption("最近下载任务：")
        for job in jobs:
            st.caption(f"{job.get('created_at')} ｜ {job.get('source_key')} ｜ {job.get('account_mode')} ｜ {job.get('status')} ｜ {job.get('stage')}")


def render_platform_admin_panel() -> None:
    if os.getenv("ENABLE_PLATFORM_ACCOUNT_ADMIN", "0").strip() not in {"1", "true", "TRUE", "yes", "on"}:
        return
    with st.expander("后台平台账号配置（管理员）", expanded=False):
        st.caption("仅在服务器环境变量 ENABLE_PLATFORM_ACCOUNT_ADMIN=1 时显示。普通用户前台不会看到平台账号明文。")
        with st.form("web_platform_account_admin_form", clear_on_submit=False):
            label = st.text_input("账号标签", value="后台地理空间数据云账号")
            username = st.text_input("平台账号用户名")
            password = st.text_input("平台账号密码", type="password")
            storage_state_path = st.text_input("storage_state 路径（可选）")
            daily_limit = st.number_input("日限额", min_value=1, value=50, step=1)
            monthly_limit = st.number_input("月限额", min_value=1, value=1000, step=10)
            submitted = st.form_submit_button("加密保存 / 更新平台账号", use_container_width=True, type="primary")
        if submitted:
            try:
                account = commercial.upsert_platform_account(
                    source_key="gscloud",
                    username=username,
                    password=password,
                    label=label,
                    daily_limit=int(daily_limit),
                    monthly_limit=int(monthly_limit),
                    storage_state_path=storage_state_path,
                )
                st.success(f"平台账号已保存：{account.get('label')} ｜ 用户名 {account.get('username_preview') or '-'}。")
            except Exception as exc:
                st.error(f"平台账号保存失败：{exc}")
        accounts = commercial.list_platform_accounts(source_key="gscloud", include_inactive=False)
        if accounts:
            for account in accounts[:8]:
                st.caption(f"{account.get('label')} ｜ {account.get('username_preview') or '-'} ｜ 日用量 {account.get('used_today')}/{account.get('daily_limit')} ｜ 月用量 {account.get('used_month')}/{account.get('monthly_limit')}")


def render_commercial_auth_panel(summary: dict | None) -> None:
    st.markdown("<div class='sidebar-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>账号与会员</div>", unsafe_allow_html=True)
    if not summary:
        st.caption("登录后可保存个人数据源账号、开通会员，并使用后台平台账号池下载数据。")
        if st.button("登录 / 注册账号", use_container_width=True, type="primary"):
            st.session_state.show_commercial_login = True
        if st.session_state.get("show_commercial_login"):
            render_login_register_forms()
    else:
        render_account_status(summary)
        action_cols = st.columns(2)
        if action_cols[0].button("刷新账号", use_container_width=True, type="tertiary"):
            st.session_state.commercial_user = commercial.permission_summary(summary["user"]["user_id"])["user"]
            st.rerun()
        if action_cols[1].button("退出登录", use_container_width=True, type="secondary"):
            try:
                commercial.logout_session(st.session_state.get("commercial_session_id", ""))
            except Exception:
                pass
            st.session_state.commercial_user = None
            st.session_state.commercial_session_id = ""
            st.session_state.commercial_session_token = ""
            st.session_state.show_commercial_login = False
            st.rerun()
        with st.expander("数据源账号 / 支付 / 下载", expanded=False):
            tab_cred, tab_pay, tab_download = st.tabs(["自有账号", "会员支付", "平台下载"])
            with tab_cred:
                render_user_credential_panel(summary)
            with tab_pay:
                render_payment_panel(summary)
            with tab_download:
                render_platform_download_panel(summary)
    render_platform_admin_panel()
    st.markdown("</div>", unsafe_allow_html=True)


def render_topbar(dashboard: dict, commercial_summary: dict | None = None) -> None:
    summary = dashboard["summary"]
    counts = dashboard.get("dataset_type_counts", {})
    if commercial_summary:
        user = commercial_summary.get("user", {})
        plan = str(user.get("plan") or "free").lower()
        account_value = f"{plan_account_type(plan)} · {plan_label(plan)}"
        account_note = str(user.get("email") or user.get("user_id") or "-")
    else:
        account_value = "未登录"
        account_note = "左侧可登录/注册"
    st.markdown(
        f"""
        <div class='app-topbar'>
            <div class='topbar-grid'>
                <div class='topbar-main'>
                    <div class='topbar-title'>GIS 专业数据产品界面</div>
                    <div class='topbar-sub'>围绕数据载入、建模对话、结果预览和导出组织页面，减少装饰噪声，突出分析流程与状态信息。</div>
                </div>
                <div class='topbar-kpi'>
                    <div class='topbar-kpi-label'>当前会话</div>
                    <div class='topbar-kpi-value'>{escape(current_session_title(dashboard))}</div>
                    <div class='topbar-kpi-note'>连续追问与阶段汇报</div>
                </div>
                <div class='topbar-kpi'>
                    <div class='topbar-kpi-label'>模型策略</div>
                    <div class='topbar-kpi-value'>{escape(dashboard.get('current_model', '-'))}</div>
                    <div class='topbar-kpi-note'>实际调用 {escape(dashboard.get('active_model', '-'))}</div>
                </div>
                <div class='topbar-kpi'>
                    <div class='topbar-kpi-label'>数据资产</div>
                    <div class='topbar-kpi-value'>{summary['dataset_count']}</div>
                    <div class='topbar-kpi-note'>矢量 {counts.get('vector', 0)} / 栅格 {counts.get('raster', 0)}</div>
                </div>
                <div class='topbar-kpi'>
                    <div class='topbar-kpi-label'>结果产物</div>
                    <div class='topbar-kpi-value'>{summary['artifact_count']}</div>
                    <div class='topbar-kpi-note'>累计操作 {summary['operation_count']} 次</div>
                </div>
                <div class='topbar-kpi'>
                    <div class='topbar-kpi-label'>账号状态</div>
                    <div class='topbar-kpi-value'>{escape(account_value)}</div>
                    <div class='topbar-kpi-note'>{escape(account_note)}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_service() -> GISWorkspaceService:
    return GISWorkspaceService()


service = get_service()
commercial = CommercialService(service.manager.workdir)


def _init_commercial_session_state() -> None:
    defaults = {
        "preview_path": "",
        "prefill": "",
        "export_result": None,
        "commercial_user": None,
        "commercial_session_id": "",
        "commercial_session_token": "",
        "show_commercial_login": False,
        "platform_env_seed_checked": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_commercial_session_state()
seed_platform_account_from_env()

def render_sidebar(dashboard: dict, commercial_summary: dict | None = None) -> None:
    summary = dashboard["summary"]
    counts = dashboard.get("dataset_type_counts", {})
    labels = session_display_labels(dashboard.get("sessions", []))
    sessions = dashboard.get("sessions", [])
    current_session = dashboard.get("current_session_id")
    session_ids = [item["session_id"] for item in sessions]

    with st.sidebar:
        st.markdown(
            f"""
            <div class='sidebar-brand'>
                <div class='sidebar-title'>GIS 智能工作台</div>
                <div class='sidebar-sub'>左侧管理会话与数据；中间专注高密度对话；右侧浏览结果图与导出文件，整体更偏专业 GIS 工作台。</div>
                <div class='badge-row'>
                    <span class='badge'>当前会话：{escape(current_session_title(dashboard))}</span>
                    <span class='badge'>模型：{escape(dashboard.get('current_model', '-'))}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        render_commercial_auth_panel(commercial_summary)

        metric_cols = st.columns(2)
        with metric_cols[0]:
            st.markdown(
                f"<div class='mini-stat'><div class='stat-label'>数据集</div><div class='stat-value accent-blue'>{summary['dataset_count']}</div><div class='muted'>矢量 {counts.get('vector', 0)} · 栅格 {counts.get('raster', 0)}</div></div>",
                unsafe_allow_html=True,
            )
        with metric_cols[1]:
            st.markdown(
                f"<div class='mini-stat'><div class='stat-label'>结果文件</div><div class='stat-value accent-violet'>{summary['artifact_count']}</div><div class='muted'>活动 {summary['operation_count']} 次</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div class='sidebar-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>项目会话</div>", unsafe_allow_html=True)
        session_action_cols = st.columns(2)
        if session_action_cols[0].button("✦ 新建对话", use_container_width=True, type="primary"):
            service.create_new_session()
            st.rerun()
        if session_action_cols[1].button("🗑 删除当前", use_container_width=True, disabled=not session_ids, type="secondary"):
            service.delete_session(current_session)
            st.rerun()

        if session_ids:
            selected_session = st.selectbox(
                "切换会话",
                options=session_ids,
                index=session_ids.index(current_session) if current_session in session_ids else 0,
                format_func=lambda x: labels.get(x, x),
            )
            if selected_session != current_session:
                service.switch_session(selected_session)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='sidebar-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>模型与工作区</div>", unsafe_allow_html=True)
        route_options = dashboard["route_options"]
        current_model = dashboard["current_model"]
        model_index = route_options.index(current_model) if current_model in route_options else 0
        selected_model = st.selectbox("模型策略", options=route_options, index=model_index)
        if selected_model != current_model:
            service.switch_model(selected_model)
            st.rerun()

        utility_cols = st.columns(2)
        if utility_cols[0].button("↻ 刷新", use_container_width=True, type="tertiary"):
            st.rerun()
        if utility_cols[1].button("⌫ 清空对话", use_container_width=True, type="secondary"):
            service.clear_current_chat()
            st.rerun()

        st.caption(f"最近一次实际调用模型：{dashboard.get('active_model', '-')}")
        runtime = dashboard.get("runtime_status", {})
        if runtime.get("busy"):
            st.info(f"{runtime.get('label', '智能体运行中')}｜{runtime.get('detail', '')}")
            st.progress(int(runtime.get("progress", 0)))
        else:
            st.caption(f"运行状态：{runtime.get('label', '就绪')}｜{runtime.get('detail', '')}")
            st.progress(int(runtime.get("progress", 0)))
        st.code(dashboard["workdir"], language="text")

        export_dir = st.text_input("导出目录（Web 端为服务器路径）", value=dashboard.get("export_dir", ""), help="Web 端无法直接替你选择浏览器本地保存路径，这里配置的是运行该应用服务器上的导出目录；浏览器本地保存位置由浏览器决定。")
        export_cols = st.columns(3)
        if export_cols[0].button("保存目录", use_container_width=True, type="tertiary"):
            try:
                service.set_export_dir(export_dir)
                st.success("导出目录已更新。")
            except Exception as exc:
                st.error(f"设置导出目录失败：{exc}")
        if export_cols[1].button("导出最新", use_container_width=True, type="secondary"):
            try:
                st.session_state.export_result = service.export_results("latest")
                st.success("最新结果已导出。")
            except Exception as exc:
                st.error(f"导出失败：{exc}")
        if export_cols[2].button("导出全部", use_container_width=True, type="secondary"):
            try:
                st.session_state.export_result = service.export_results("all")
                st.success("全部结果已导出。")
            except Exception as exc:
                st.error(f"导出失败：{exc}")
        export_result = st.session_state.get("export_result")
        if export_result:
            st.caption(f"最近导出：{export_result.get('file_count', 0)} 个文件")
            st.code(export_result.get("export_dir", ""), language="text")
            zip_path = Path(export_result.get("zip_path", ""))
            if zip_path.exists():
                with open(zip_path, "rb") as file_obj:
                    st.download_button("下载最近导出 ZIP", data=file_obj.read(), file_name=zip_path.name, use_container_width=True, type="primary")

        st.divider()
        task_cols = st.columns([2, 1])
        task_cols[0].markdown("**外部下载/导出任务**")
        if task_cols[1].button("刷新任务", use_container_width=True, type="tertiary"):
            st.session_state.export_tasks = service.refresh_export_tasks(limit=8)
            st.rerun()
        export_tasks_payload = st.session_state.get("export_tasks")
        if not export_tasks_payload:
            export_tasks_payload = {"items": dashboard.get("recent_export_tasks", [])}
        tasks = export_tasks_payload.get("items", []) if isinstance(export_tasks_payload, dict) else []
        task_error = export_tasks_payload.get("message", "") if isinstance(export_tasks_payload, dict) else ""
        if task_error:
            st.caption(f"刷新提示：{task_error}")
        if tasks:
            for task in tasks[:4]:
                dest = task.get("destination", {}) or {}
                dest_text = dest.get("type", "-")
                if dest.get("folder"):
                    dest_text += f" · {dest.get('folder')}"
                elif dest.get("bucket"):
                    dest_text += f" · {dest.get('bucket')}"
                st.markdown(
                    f"<div class='artifact-card'><div><strong>{escape(str(task.get('dataset_name') or '-'))}</strong></div>"
                    f"<div class='muted'>状态：{escape(str(task.get('task_state') or 'UNKNOWN'))}</div>"
                    f"<div class='muted'>目标：{escape(dest_text)}</div>"
                    f"<div class='muted'>Task ID：{escape(str(task.get('task_id') or '-'))}</div></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("当前还没有批量导出任务。")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='sidebar-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>上传数据</div>", unsafe_allow_html=True)
        st.caption("支持 shp/shx/dbf/prj/cpg、GeoJSON、栅格、表格、zip 与文档，适合分析、建模、图表与论文材料整理。")
        uploads = st.file_uploader(
            "上传 GIS / 文档数据",
            accept_multiple_files=True,
            type=["shp", "shx", "dbf", "prj", "cpg", "geojson", "gpkg", "json", "kml", "tif", "tiff", "img", "csv", "xlsx", "xls", "zip", "docx", "txt", "md"],
        )
        if uploads:
            try:
                messages = service.upload_bytes_batch([(uploaded.name, uploaded.getvalue()) for uploaded in uploads])
                for msg in messages:
                    service.append_system_message(msg)
            except Exception as exc:
                st.error(f"文件加载失败：{exc}")
            else:
                st.success("文件已加载到工作区。")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='sidebar-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>快捷任务</div><div class='muted' style='margin-bottom:0.55rem'>把常用分析做成高识别度的快捷入口。</div>", unsafe_allow_html=True)
        for suggestion in dashboard.get("suggestions", []):
            if st.button(f"⚡ {suggestion}", use_container_width=True, type="tertiary"):
                st.session_state.prefill = suggestion

        st.markdown(
            """
            <div style='margin-top:0.7rem'>
                <span class='hint-chip'>空间分析</span>
                <span class='hint-chip'>图表导出</span>
                <span class='hint-chip'>XGBoost 建模</span>
                <span class='hint-chip'>论文表达</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)


def render_message_meta(meta: dict) -> None:
    if not meta:
        return
    mode_text = "自动选择" if meta.get("mode") == "auto" else "手动指定"
    images = meta.get("images") or []
    image_text = "、".join(Path(path).name for path in images)
    st.markdown(
        f"""
        <div class='meta-card'>
            <div class='caption-line'><b>模型：</b>{escape(str(meta.get('model', '-')))} ｜ <b>模式：</b>{escape(mode_text)}</div>
            <div class='caption-line' style='margin-top:0.22rem'>{escape(str(meta.get('reason', '')))}</div>
            {f"<div class='caption-line' style='margin-top:0.22rem'>附带图件：{escape(image_text)}</div>" if image_text else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dataset_list(datasets: list[dict]) -> None:
    if not datasets:
        st.markdown("<div class='empty-card'>当前还没有已加载数据。</div>", unsafe_allow_html=True)
        return
    for item in datasets:
        with st.expander(f"{item['name']} · {item['type']}", expanded=False):
            st.markdown(
                f"<div class='dataset-card'><div class='dataset-title'>{escape(item['name'])}</div><div class='muted'>{escape(item['path'])}</div></div>",
                unsafe_allow_html=True,
            )
            st.code(json.dumps(item.get("meta", {}), ensure_ascii=False, indent=2), language="json")


def render_artifact_list(artifacts: list[dict]) -> None:
    if not artifacts:
        st.markdown("<div class='empty-card'>当前还没有生成结果文件。</div>", unsafe_allow_html=True)
        return
    for item in artifacts[:24]:
        path = Path(item["path"])
        st.markdown(
            f"<div class='artifact-card'><div class='artifact-title'>{escape(item['name'])}</div><div class='muted'>{escape(item['category'])} · {item['size_kb']} KB · {escape(item['modified'])}<br><span class='muted'>{escape(item.get('display_path', item['path']))}</span></div></div>",
            unsafe_allow_html=True,
        )
        action_cols = st.columns([1, 1, 3])
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            if action_cols[0].button("预览", key=f"preview_{item['path']}", use_container_width=True, type="primary"):
                st.session_state.preview_path = item["path"]
        with open(path, "rb") as file_obj:
            action_cols[1].download_button("下载", data=file_obj.read(), file_name=path.name, key=f"download_{item['path']}", use_container_width=True, type="secondary")


def render_activity_list(activity: list[dict]) -> None:
    if not activity:
        st.markdown("<div class='empty-card'>暂无活动记录。</div>", unsafe_allow_html=True)
        return
    for item in activity[:18]:
        st.markdown(
            f"<div class='activity-card'><div class='artifact-title'>{escape(item['time'])} · {escape(item['title'])}</div><div class='muted'>{escape(item['detail'] or '')}</div></div>",
            unsafe_allow_html=True,
        )


def render_pipeline(latest_pipeline: dict | None, db_info: dict) -> None:
    st.markdown("<div class='dock-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>流水线</div>", unsafe_allow_html=True)
    st.caption(f"SQLite：{db_info.get('db_path', '')}")
    st.write(
        f"数据集 {db_info.get('catalog_count', 0)} ｜ SQL 表 {db_info.get('sql_table_count', 0)} ｜ 流水线 {db_info.get('pipeline_run_count', 0)} ｜ 会话 {db_info.get('conversation_count', 0)}"
    )
    if latest_pipeline:
        st.markdown(f"**最近一次运行：** {latest_pipeline.get('run_id', '')}")
        st.caption(f"状态：{latest_pipeline.get('status', '')} ｜ 输出前缀：{latest_pipeline.get('output_prefix', '')}")
        for step in latest_pipeline.get("steps", [])[:10]:
            st.markdown(f"- {step.get('step_order')}. {step.get('step_name')}（{step.get('status')}）")
            if step.get("output_summary"):
                st.caption(step.get("output_summary"))
    else:
        st.markdown("<div class='empty-card'>当前还没有训练流水线记录。</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_right_dock(dashboard: dict) -> None:
    summary = dashboard["summary"]
    preview_path = st.session_state.get("preview_path") or dashboard.get("last_plot")

    st.markdown("<div class='main-right-anchor'></div><div class='dock-root'>", unsafe_allow_html=True)

    st.markdown("<div class='dock-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>结果图浏览</div><div class='muted' style='margin-bottom:0.48rem'>右侧保留结果图预览、结果文件和导出操作，结构更接近专业数据产品的分析面板。</div>", unsafe_allow_html=True)
    st.markdown("<div class='result-hero'><div class='result-hero-title'>结果预览面板</div><div class='result-hero-sub'>优先展示当前会话最新图表或地图；下方结果浏览页签用于切换预览与下载。</div></div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='muted' style='margin-bottom:0.55rem'>当前会话：{escape(current_session_title(dashboard))} · 模型 {escape(dashboard.get('current_model', '-'))}</div>",
        unsafe_allow_html=True,
    )
    if preview_path and Path(preview_path).exists():
        st.image(preview_path, use_container_width=True)
        st.caption(preview_path)
    else:
        st.markdown("<div class='empty-card'>暂无图表或地图可预览。</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='muted' style='margin-top:0.35rem'>当前工作区共有 {summary['artifact_count']} 个结果文件，可在下方列表中预览或下载。</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    tab_result, tab_files = st.tabs(["🖼 结果浏览", "📦 文件导出"])
    with tab_result:
        render_artifact_list(dashboard.get("artifacts", []))
    with tab_files:
        st.markdown(
            f"<div class='dock-card'><div class='section-title'>工作目录</div><div class='muted'>{escape(dashboard['workdir'])}</div></div>",
            unsafe_allow_html=True,
        )
        st.code(dashboard["workdir"], language="text")
        tasks = dashboard.get("recent_export_tasks", [])
        if tasks:
            st.markdown("<div class='section-title' style='margin-top:0.6rem'>最近导出任务</div>", unsafe_allow_html=True)
            for task in tasks[:5]:
                dest = task.get("destination", {}) or {}
                dest_text = dest.get("type", "-")
                if dest.get("folder"):
                    dest_text += f" · {dest.get('folder')}"
                elif dest.get("bucket"):
                    dest_text += f" · {dest.get('bucket')}"
                st.markdown(
                    f"<div class='artifact-card'><div><strong>{escape(str(task.get('dataset_name') or '-'))}</strong></div>"
                    f"<div class='muted'>状态：{escape(str(task.get('task_state') or 'UNKNOWN'))}</div>"
                    f"<div class='muted'>目标：{escape(dest_text)}</div></div>",
                    unsafe_allow_html=True,
                )

    st.markdown("</div>", unsafe_allow_html=True)

def render_chat(dashboard: dict) -> None:
    st.markdown("<div class='chat-root-anchor'></div>", unsafe_allow_html=True)
    messages = dashboard.get("messages", [])
    runtime = dashboard.get("runtime_status", {})

    st.markdown(
        """
        <div class='chat-hero'>
            <div class='hero-title'>智能分析对话区</div>
            <div class='hero-sub'>把任务描述、追问、图表要求和论文表达放在这里；输入内容与智能体输出会以不同风格显示，方便快速扫读。</div>
        </div>
        <div class='product-strip'>
            <span class='product-pill'>模型训练</span>
            <span class='product-pill'>空间分析</span>
            <span class='product-pill'>GCP 不确定性</span>
            <span class='product-pill'>图表与论文材料</span>
        </div>
        <div class='input-toolbar'>
            <div class='toolbar-title'>分析模式快捷入口</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if runtime.get("busy"):
        st.warning(f"{runtime.get('label', '智能体运行中')}：{runtime.get('detail', '')}")
        st.progress(int(runtime.get("progress", 0)))

    tool_cols = st.columns(4)
    tool_prompts = [
        ("训练 XGBoost", "请基于当前上传数据训练 XGBoost 空间回归模型，并输出预测结果、特征重要性、精度指标和残差分析。"),
        ("执行 GCP", "请在现有模型结果基础上执行 GCP 不确定性分析，输出区间结果与 PICP、MPIW、NMPIW、QCP、IS。"),
        ("生成图表", "请根据当前结果生成论文风格图表，并补充图注说明。"),
        ("整理汇报", "请把当前分析整理成答辩可用的阶段汇报，区分点预测结果与 GCP 不确定性结果。"),
    ]
    for col, (label, prompt_text) in zip(tool_cols, tool_prompts):
        with col:
            if st.button(label, use_container_width=True, type="tertiary"):
                st.session_state.prefill = prompt_text

    if messages:
        toolbar_cols = st.columns([1, 1, 4])
        with toolbar_cols[0]:
            render_copy_button("复制全部", format_conversation_text(messages), "copy_all_messages")
        latest_reply = latest_assistant_text(messages)
        if latest_reply:
            with toolbar_cols[1]:
                render_copy_button("复制最近结果", latest_reply, "copy_latest_reply")
    else:
        st.markdown("<div class='empty-card'>当前对话为空。直接在底部输入任务即可开始分析。</div>", unsafe_allow_html=True)

    for message in messages:
        role = message["role"] if message["role"] in {"user", "assistant", "system"} else "system"
        with st.chat_message(role, avatar="🧭" if role == "assistant" else ("👤" if role == "user" else "⚙️")):
            if role == "assistant":
                st.markdown("<div class='msg-assistant-anchor'></div><div class='msg-role-pill assistant-pill'>智能体输出</div>", unsafe_allow_html=True)
                render_message_meta(message.get("meta", {}))
            elif role == "user":
                st.markdown("<div class='msg-user-anchor'></div><div class='msg-role-pill user-pill'>你的输入</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='msg-system-anchor'></div><div class='msg-role-pill system-pill'>系统消息</div>", unsafe_allow_html=True)
            render_copy_button("复制", message.get("content", ""), f"msg_{message.get('message_id', 'x')}")
            st.markdown(message.get("content", ""))

    prompt = st.chat_input("输入 GIS 任务、继续追问，或要求输出图表 / 地图 / 统计结果")
    if not prompt:
        prompt = st.session_state.pop("prefill", None)

    if prompt:
        with st.chat_message("user", avatar="👤"):
            st.markdown("<div class='msg-user-anchor'></div><div class='msg-role-pill user-pill'>你的输入</div>", unsafe_allow_html=True)
            render_copy_button("复制", prompt, "pending_user_prompt")
            st.markdown(prompt)
        with st.chat_message("assistant", avatar="🧭"):
            st.markdown("<div class='msg-assistant-anchor'></div><div class='msg-role-pill assistant-pill'>智能体输出</div>", unsafe_allow_html=True)
            status = st.status("智能体正在运行", expanded=True)
            status.write("已收到任务，正在解析意图与选择模型…")
            try:
                result = service.ask(prompt)
                status.write("模型与 GIS 工具执行完成，正在刷新结果面板…")
                status.update(label="智能体运行完成", state="complete", expanded=False)
                render_message_meta(result)
                render_copy_button("复制", result["reply"], "pending_assistant_reply")
                st.markdown(result["reply"])
            except Exception as exc:
                status.update(label="智能体运行失败", state="error", expanded=True)
                st.error(str(exc))
        st.rerun()


dashboard = service.dashboard()
commercial_summary = get_commercial_summary()
render_topbar(dashboard, commercial_summary)
render_sidebar(dashboard, commercial_summary)

center_col, right_col = st.columns([2.15, 0.72], gap="medium")

with center_col:
    st.markdown("<div class='main-center-anchor'></div>", unsafe_allow_html=True)
    render_chat(dashboard)
with right_col:
    render_right_dock(dashboard)
