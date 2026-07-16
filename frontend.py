import json
import uuid

import requests
import streamlit as st

from src.logger import configure_logging, get_logger

# -----------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------
configure_logging()
logger = get_logger(__name__)

APP_NAME = "Corpus"  # ← change this one line to rename the app everywhere

st.set_page_config(page_title=f"{APP_NAME} · Document assistant", page_icon="💬", layout="wide")

# -----------------------------------------------------------------------
# Design system — one accent color, consistent spacing, quiet chrome.
# Streamlit lets us reach the DOM via unsafe CSS injection; everything
# below targets stable data-testid hooks rather than generated class
# names, so it survives Streamlit version bumps better than most
# CSS-injection hacks.
# -----------------------------------------------------------------------
ACCENT = "#2F6FED"
ACCENT_DARK = "#1F4FB8"

st.markdown(
    f"""
    <style>
      :root {{
        --accent: {ACCENT};
        --accent-dark: {ACCENT_DARK};
        /* Muted text: dark gray on light backgrounds by default */
        --muted-text: rgba(49, 51, 63, 0.6);
        --muted-border: rgba(49, 51, 63, 0.1);
      }}
      /* Streamlit's dark theme sets a near-black app background; detect it
         via prefers-color-scheme so muted text stays legible either way.
         (Best-effort: this follows the OS setting, which usually matches
         Streamlit's theme toggle but isn't guaranteed to in every setup.) */
      @media (prefers-color-scheme: dark) {{
        :root {{
          --muted-text: rgba(250, 250, 250, 0.6);
          --muted-border: rgba(250, 250, 250, 0.15);
        }}
      }}

      /* Sidebar */
      section[data-testid="stSidebar"] {{
        border-right: 1px solid var(--muted-border);
      }}
      section[data-testid="stSidebar"] h3 {{
        font-size: 0.75rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted-text);
        font-weight: 600;
        margin-bottom: 0.5rem;
      }}

      /* Primary buttons (login, send, etc.) get the single accent color */
      button[kind="primary"] {{
        background-color: var(--accent) !important;
        border-color: var(--accent) !important;
      }}
      button[kind="primary"]:hover {{
        background-color: var(--accent-dark) !important;
        border-color: var(--accent-dark) !important;
      }}

      /* Active session row */
      .session-active button {{
        border-color: var(--accent) !important;
        color: var(--accent) !important;
        font-weight: 600 !important;
      }}

      /* Empty-state hero on the main canvas */
      .empty-state {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        padding: 4rem 1rem;
        color: inherit;
      }}
      .empty-state .icon {{
        width: 44px;
        height: 44px;
        border-radius: 10px;
        background: rgba(47, 111, 237, 0.12);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        margin-bottom: 1rem;
      }}
      .empty-state h2 {{
        font-size: 1.25rem;
        margin: 0 0 0.5rem;
      }}
      .empty-state p {{
        max-width: 420px;
        color: var(--muted-text);
        font-size: 0.95rem;
        line-height: 1.6;
        margin: 0;
      }}

      /* Debug metadata under assistant replies — de-emphasized, monospace */
      .response-meta {{
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
        font-size: 0.72rem;
        color: var(--muted-text);
        margin-top: -0.25rem;
      }}

      /* Session id footer */
      .session-id {{
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
        font-size: 0.72rem;
        color: var(--muted-text);
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


def get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


DEFAULT_BACKEND_URL = get_secret("BACKEND_URL", "http://localhost:8000")


def _get_query_params() -> dict[str, str]:
    try:
        params = st.query_params
        return {key: str(value) for key, value in params.items() if value is not None}
    except Exception:
        try:
            params = st.experimental_get_query_params()
            return {key: value[0] for key, value in params.items() if value}
        except Exception:
            return {}


def _set_query_param(key: str, value: str) -> None:
    try:
        st.query_params[key] = value
    except Exception:
        try:
            st.experimental_set_query_params(**{key: value})
        except Exception:
            pass


def _clear_query_params() -> None:
    try:
        st.query_params.clear()
    except Exception:
        try:
            st.experimental_set_query_params()
        except Exception:
            pass


backend_url = DEFAULT_BACKEND_URL.rstrip("/")


# -----------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------
if "auth_token" not in st.session_state:
    st.session_state.auth_token = ""
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

_persisted = _get_query_params()
if not st.session_state.auth_token and _persisted.get("auth_token"):
    st.session_state.auth_token = _persisted.get("auth_token", "")
if st.session_state.auth_user is None and _persisted.get("auth_user"):
    try:
        st.session_state.auth_user = json.loads(_persisted["auth_user"])
    except json.JSONDecodeError:
        st.session_state.auth_user = None
if _persisted.get("current_session_id"):
    st.session_state.current_session_id = _persisted["current_session_id"]


def is_authenticated() -> bool:
    return bool(st.session_state.auth_token)


def logout_user() -> None:
    logger.info("Logging out current frontend session")
    st.session_state.auth_token = ""
    st.session_state.auth_user = None
    st.session_state.current_session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.pop("_last_meta", None)
    _clear_query_params()


def start_new_chat() -> None:
    st.session_state.current_session_id = str(uuid.uuid4())
    logger.info("Starting new frontend chat session: session_id=%s", st.session_state.current_session_id)
    st.session_state.messages = []
    _set_query_param("current_session_id", st.session_state.current_session_id)


def switch_session(session_id: str) -> None:
    logger.info("Switching frontend session: session_id=%s", session_id)
    st.session_state.current_session_id = session_id
    st.session_state.messages = load_session_history(session_id)
    _set_query_param("current_session_id", session_id)


def auth_headers() -> dict[str, str]:
    if not is_authenticated():
        return {}
    return {
        "Authorization": f"Bearer {st.session_state.auth_token}",
        "Content-Type": "application/json",
    }


def public_headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


def _request_json(
    method: str,
    path: str,
    *,
    json_payload=None,
    auth: bool = False,
    stream: bool = False,
):
    url = f"{backend_url}{path}"
    logger.debug("Frontend request: method=%s path=%s auth=%s stream=%s", method, path, auth, stream)
    headers = auth_headers() if auth else public_headers()
    response = requests.request(
        method,
        url,
        headers=headers,
        json=json_payload,
        stream=stream,
        timeout=120 if stream else 10,
    )
    if response.status_code == 401 and auth:
        logger.warning("Frontend request unauthorized: method=%s path=%s", method, path)
        logout_user()
        raise requests.HTTPError("Session expired. Please sign in again.")
    response.raise_for_status()
    return response


# -----------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------
def _extract_error_detail(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, str) and detail:
                return detail
    except Exception:
        pass
    text = response.text.strip()
    return text or f"HTTP {response.status_code}"


def login_user(email: str, password: str) -> None:
    logger.debug("Frontend login attempt for email=%s", email.strip().lower())
    response = requests.post(
        f"{backend_url}/auth/login",
        headers=public_headers(),
        json={"email": email, "password": password},
        timeout=10,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_error_detail(response))
    data = response.json()
    logger.info("Frontend login succeeded for email=%s", data["user"].get("email"))
    st.session_state.auth_token = data["access_token"]
    st.session_state.auth_user = data["user"]
    _set_query_param("auth_token", data["access_token"])
    _set_query_param("auth_user", json.dumps(data["user"]))
    start_new_chat()


def signup_user(email: str, password: str) -> None:
    logger.debug("Frontend signup attempt for email=%s", email.strip().lower())
    response = requests.post(
        f"{backend_url}/auth/signup",
        headers=public_headers(),
        json={"email": email, "password": password},
        timeout=10,
    )
    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        if response.status_code == 409 or "already registered" in detail.lower():
            raise ValueError("User already exists")
        raise RuntimeError(detail)
    data = response.json()
    logger.info("Frontend signup succeeded for email=%s", data["user"].get("email"))
    st.session_state.auth_token = data["access_token"]
    st.session_state.auth_user = data["user"]
    _set_query_param("auth_token", data["access_token"])
    _set_query_param("auth_user", json.dumps(data["user"]))
    start_new_chat()


# -----------------------------------------------------------------------
# Backend calls
# -----------------------------------------------------------------------
def fetch_sessions() -> list[dict]:
    if not is_authenticated():
        return []
    logger.debug("Fetching sessions for authenticated frontend user")
    try:
        response = _request_json("GET", "/getSessionMetaData", auth=True)
        data = response.json()
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        logger.info("Fetched frontend sessions: count=%s", len(sessions))
        return sessions
    except requests.RequestException as e:
        st.sidebar.error(f"Couldn't load sessions: {e}")
        return []


def load_session_history(session_id: str) -> list[dict]:
    if not is_authenticated():
        return []
    logger.debug("Loading frontend session history: session_id=%s", session_id)
    try:
        response = requests.get(
            f"{backend_url}/getSessionHistory",
            headers=auth_headers(),
            params={"session_id": session_id},
            timeout=10,
        )
        if response.status_code == 401:
            logout_user()
            st.sidebar.error("Session expired. Please sign in again.")
            return []
        if response.status_code == 404:
            return []
        response.raise_for_status()
        history = response.json().get("history", [])
        logger.info("Loaded frontend session history: session_id=%s count=%s", session_id, len(history))
        return [
            {
                "role": "user" if item["role"] == "Human" else "assistant",
                "content": item["content"],
            }
            for item in history
        ]
    except requests.RequestException as e:
        st.sidebar.error(f"Couldn't load history: {e}")
        return []


def _hydrate_session_from_persistence() -> None:
    """Restore chat history for the session id carried over in the URL,
    but only if that session id still belongs to the signed-in user."""
    if not is_authenticated():
        return
    if st.session_state.messages:
        return
    sessions = fetch_sessions()
    session_ids = {s.get("session_id") for s in sessions if s.get("session_id")}
    current_session_id = st.session_state.current_session_id
    if current_session_id and current_session_id in session_ids:
        st.session_state.messages = load_session_history(current_session_id)


_hydrate_session_from_persistence()


def stream_chat_response(session_id: str, user_query: str):
    if not is_authenticated():
        yield "Sign in to continue."
        return

    logger.debug("Streaming frontend chat request: session_id=%s query_len=%s", session_id, len(user_query))
    payload = {"session_id": session_id, "user_query": user_query}
    saw_token = False
    try:
        with requests.post(
            f"{backend_url}/chat/stream",
            headers=auth_headers(),
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            if resp.status_code == 401:
                logger.warning("Frontend stream unauthorized: session_id=%s", session_id)
                logout_user()
                yield "\n\n*(session expired — sign in again)*"
                return
            resp.raise_for_status()
            event_name = None
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("event:"):
                    event_name = raw_line.split("event:", 1)[1].strip()
                elif raw_line.startswith("data:"):
                    data_str = raw_line.split("data:", 1)[1].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event_name == "token":
                        token = data.get("token", "")
                        if token:
                            saw_token = True
                            yield token
                    elif event_name == "done":
                        st.session_state["_last_meta"] = data
                        if not saw_token:
                            fallback_answer = (data.get("answer") or "").strip()
                            if fallback_answer:
                                saw_token = True
                                yield fallback_answer
    except requests.RequestException as e:
        logger.exception("Frontend stream request failed: session_id=%s", session_id)
        st.session_state["_last_meta"] = None
        yield f"\n\n*(couldn't reach the backend: {e})*"


# -----------------------------------------------------------------------
# Sidebar: auth and sessions
# -----------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Account")

    if is_authenticated():
        user = st.session_state.auth_user or {}
        st.markdown(f"Signed in as **{user.get('email', 'unknown')}**")
        if st.button("Log out", use_container_width=True):
            logout_user()
            st.rerun()
    else:
        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

        with login_tab:
            with st.form("login_form", clear_on_submit=True):
                login_email = st.text_input("Email", key="login_email", placeholder="name@company.com")
                login_password = st.text_input(
                    "Password", key="login_password", type="password", placeholder="••••••••"
                )
                login_submit = st.form_submit_button(
                    "Log in", use_container_width=True, type="primary"
                )
            if login_submit:
                try:
                    login_user(login_email, login_password)
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Login failed: {exc}")
                except RuntimeError as exc:
                    st.error(f"Login failed: {exc}")

        with signup_tab:
            with st.form("signup_form", clear_on_submit=True):
                signup_email = st.text_input("Email", key="signup_email", placeholder="name@company.com")
                signup_password = st.text_input(
                    "Password", key="signup_password", type="password", placeholder="At least 8 characters"
                )
                signup_submit = st.form_submit_button(
                    "Create account", use_container_width=True, type="primary"
                )
            if signup_submit:
                try:
                    signup_user(signup_email, signup_password)
                    st.rerun()
                except ValueError:
                    st.warning("That email's already registered. Log in instead.")
                except RuntimeError as exc:
                    st.error(f"Sign up failed: {exc}")
                except requests.RequestException as exc:
                    st.error(f"Sign up failed: {exc}")

    st.divider()
    st.markdown("### Sessions")

    if st.button(
        "New chat",
        use_container_width=True,
        disabled=not is_authenticated(),
        icon=":material/add:",
    ):
        start_new_chat()
        st.rerun()

    if not is_authenticated():
        st.caption("Log in to see your past conversations here.")
    else:
        sessions = fetch_sessions()
        if not sessions:
            st.caption("No saved chats yet. Send a message to start one.")
        for s in sessions:
            session_id = s["session_id"]
            title = (s.get("title") or "").strip() or f"Chat {session_id[:8]}"
            is_current = session_id == st.session_state.current_session_id
            if is_current:
                st.markdown('<div class="session-active">', unsafe_allow_html=True)
            if st.button(title, key=f"session_{session_id}", use_container_width=True):
                switch_session(session_id)
                st.rerun()
            if is_current:
                st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.markdown(
        f'<span class="session-id">Session {st.session_state.current_session_id[:8]}</span>',
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------
# Main chat area
# -----------------------------------------------------------------------
st.title(APP_NAME)

if not is_authenticated():
    st.markdown(
        """
        <div class="empty-state">
            <div class="icon">💬</div>
            <h2>Ask anything about your documents</h2>
            <p>Log in or create an account on the left to start a conversation.
            Your chat history will show up here.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

if not st.session_state.messages:
    st.markdown(
        """
        <div class="empty-state">
            <div class="icon">💬</div>
            <h2>Start a new conversation</h2>
            <p>Type a message below to get going.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask a question about your documents..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        answer = st.write_stream(
            stream_chat_response(st.session_state.current_session_id, prompt)
        )

    st.session_state.messages.append({"role": "assistant", "content": answer})

    meta = st.session_state.pop("_last_meta", None)
    if meta:
        latency = meta.get("latency")
        latency_str = f"{latency:.2f}s" if isinstance(latency, (int, float)) else "n/a"
        st.markdown(
            f'<div class="response-meta">{meta.get("model", "unknown")} '
            f'· {meta.get("tokens", "n/a")} tokens · {latency_str}</div>',
            unsafe_allow_html=True,
        )