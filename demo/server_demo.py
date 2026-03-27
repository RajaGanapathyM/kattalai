"""
Kattalai — Runtime API demo
Run:
    pip install streamlit requests
    streamlit run agent_shell_ui.py
"""

import time
import requests
import streamlit as st

BASE = "http://127.0.0.1:3077"
POLL_INTERVAL = 1.5   # seconds between is_working checks

st.set_page_config(
    page_title="Kattalai",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API helpers ──────────────────────────────────────────────────────────────

def api(path: str, body: dict | None = None, timeout: int = 10):
    try:
        r = requests.post(f"{BASE}{path}", json=body, timeout=timeout)
        j = r.json()
        if j.get("ok"):
            return j["data"], None
        return None, j.get("error", "unknown error")
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach Runtime at {BASE}"
    except Exception as e:
        return None, str(e)

def is_agent_working() -> bool:
    if not (st.session_state.topic_id and st.session_state.agent_id):
        return False
    data, err = api("/agent/working-status", {
        "topic_id": st.session_state.topic_id,
        "agent_id": st.session_state.agent_id,
    })
    return bool(data) if not err else False

def flush_agent_memory():
    """Collect all new memory nodes since last poll_index."""
    mem_data, mem_err = api("/agent/iter-memory", {
        "topic_id":    st.session_state.topic_id,
        "agent_id":    st.session_state.agent_id,
        "start_index": st.session_state.poll_index,
    }, timeout=30)
    if mem_err:
        log("iter_agent_memory", mem_err)
        return
    if mem_data:
        for node in mem_data:
            text = (
                node.get("content") or
                node.get("message") or
                node.get("text")    or
                str(node)
            )
            st.session_state.messages.append({"role": "assistant", "text": text})
        st.session_state.poll_index += len(mem_data)
        log("iter_agent_memory", f"{len(mem_data)} new nodes")

# ── Session state ────────────────────────────────────────────────────────────

defaults = {
    "user_id":      None,
    "user_name":    "",
    "topic_id":     None,
    "agent_id":     None,
    "agent_name":   "",
    "messages":     [],
    "log":          [],
    "poll_index":   0,
    "waiting":      False,   # True while polling agent working status
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def log(action: str, result):
    st.session_state.log.insert(0, f"[{action}] → {result}")
    if len(st.session_state.log) > 40:
        st.session_state.log.pop()

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⬡ Kattalai")
    st.caption("Runtime API demo")
    st.divider()

    st.markdown("### 1 · User")
    uname = st.text_input("Username", value=st.session_state.user_name, key="uname_input")
    if st.button("Create User", use_container_width=True):
        data, err = api("/user/create", {"user_name": uname})
        if err:
            st.error(err)
        else:
            st.session_state.user_id   = data
            st.session_state.user_name = uname
            log("create_user", data)
            st.success(f"uid: {data[:12]}…")
    if st.session_state.user_id:
        st.caption(f"✓ `{st.session_state.user_id[:16]}…`")

    st.divider()

    st.markdown("### 2 · Topic")
    if st.button("New Topic Thread", use_container_width=True):
        data, err = api("/topic/create")
        if err:
            st.error(err)
        else:
            st.session_state.topic_id   = data
            st.session_state.messages   = []
            st.session_state.poll_index = 0
            st.session_state.waiting    = False
            log("create_topic", data)
            st.success(f"tid: {data[:12]}…")
    if st.session_state.topic_id:
        st.caption(f"✓ `{st.session_state.topic_id[:16]}…`")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("History len", use_container_width=True):
                data, err = api("/topic/history-len", {"topic_id": st.session_state.topic_id})
                log("topic_history_len", err or data)
                if err: st.error(err)
                else:   st.info(f"{data} messages")
        with col2:
            if st.button("Iter topic", use_container_width=True):
                data, err = api("/topic/iter", {
                    "topic_id":    st.session_state.topic_id,
                    "start_index": 0,
                })
                log("iter_topic", err or f"{len(data)} nodes")
                if err: st.error(err)

    st.divider()

    st.markdown("### 3 · Agent")
    data_agents, _ = api("/agents/list")
    agent_options   = data_agents if isinstance(data_agents, list) else []
    if agent_options:
        chosen = st.selectbox("Available agents", agent_options)
    else:
        chosen = st.text_input("Agent name (manual)", key="agent_manual")
    if st.button("Deploy Agent", use_container_width=True):
        if not chosen:
            st.warning("Enter an agent name")
        else:
            data, err = api("/agent/deploy", {"agent_name": chosen})
            if err:
                st.error(err)
            else:
                st.session_state.agent_id   = data
                st.session_state.agent_name = chosen
                log("deploy_agent", data)
                st.success(f"aid: {data[:12]}…")
    if st.session_state.agent_id:
        st.caption(f"✓ `{st.session_state.agent_id[:16]}…`")

    st.divider()

    st.markdown("### 4 · Connect")
    ready = st.session_state.topic_id and st.session_state.agent_id
    col3, col4 = st.columns(2)
    with col3:
        if st.button("Attach", disabled=not ready, use_container_width=True):
            data, err = api("/topic/add-agent", {
                "topic_id": st.session_state.topic_id,
                "agent_id": st.session_state.agent_id,
            })
            log("add_agent_to_topic", err or data)
            if err: st.error(err)
            else:   st.success("Attached")
    with col4:
        if st.button("Detach", disabled=not ready, use_container_width=True):
            data, err = api("/topic/remove-agent", {
                "topic_id": st.session_state.topic_id,
                "agent_id": st.session_state.agent_id,
            })
            log("remove_agent_from_topic", err or data)
            if err: st.error(err)
            else:   st.warning("Detached")

    if ready:
        if st.button("Episode history len", use_container_width=True):
            data, err = api("/agent/episode-history-len", {
                "topic_id": st.session_state.topic_id,
                "agent_id": st.session_state.agent_id,
            })
            log("episode_history_len", err or data)
            if err: st.error(err)
            else:   st.info(f"{data} nodes")
        if st.button("Iter agent memory", use_container_width=True):
            data, err = api("/agent/iter-memory", {
                "topic_id":    st.session_state.topic_id,
                "agent_id":    st.session_state.agent_id,
                "start_index": 0,
            })
            log("iter_agent_memory", err or f"{len(data)} nodes")
            if err: st.error(err)

# ── Main chat area ────────────────────────────────────────────────────────────

st.markdown("## 💬 Chat")

c1, c2, c3 = st.columns(3)
c1.metric("User",  st.session_state.user_name or "—")
c2.metric("Topic", (st.session_state.topic_id[:10] + "…") if st.session_state.topic_id else "—")
c3.metric("Agent", st.session_state.agent_name or "—")

st.divider()

# ── Chat history ──────────────────────────────────────────────────────────────

chat_box = st.container(height=420)
with chat_box:
    if not st.session_state.messages:
        st.caption("No messages yet. Complete setup in sidebar, then send a message.")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])

# ── Thinking indicator + poll loop ────────────────────────────────────────────
#
# How it works:
#   1. User sends message → waiting = True → st.rerun()
#   2. On every rerun while waiting=True, this block runs:
#      - renders the spinner (blocks for POLL_INTERVAL seconds)
#      - calls is_agent_working()
#      - if still working  → st.rerun() again (keeps spinner alive)
#      - if done           → flush memory, waiting=False, st.rerun()
#   3. Chat input is disabled while waiting=True

status_slot = st.empty()

if st.session_state.waiting:
    with status_slot.container():
        with st.spinner("⚙ Agent is thinking…"):
            time.sleep(POLL_INTERVAL)
            still_working = is_agent_working()
            log("is_agent_working", still_working)

    if still_working:
        st.rerun()
    else:
        flush_agent_memory()
        st.session_state.waiting = False
        st.rerun()

# ── Chat input ────────────────────────────────────────────────────────────────

all_ready = (
    st.session_state.user_id  and
    st.session_state.topic_id and
    st.session_state.agent_id and
    not st.session_state.waiting
)

hint = (
    "⚙ Agent is thinking, please wait…" if st.session_state.waiting else
    "Complete setup in the sidebar first" if not (st.session_state.user_id and st.session_state.topic_id and st.session_state.agent_id) else
    "Type a message…"
)

prompt = st.chat_input(hint, disabled=not all_ready)

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})

    data, err = api("/message/insert", {
        "topic_id": st.session_state.topic_id,
        "user_id":  st.session_state.user_id,
        "message":  prompt,
    }, timeout=30)
    log("insert_message", err or data)

    if err:
        st.session_state.messages.append({"role": "assistant", "text": f"⚠ {err}"})
        st.rerun()
    else:
        st.session_state.waiting = True   # hand off to the poll loop above
        st.rerun()

# ── API log ───────────────────────────────────────────────────────────────────

with st.expander("🔌 API call log", expanded=False):
    if st.session_state.log:
        st.code("\n".join(st.session_state.log), language=None)
    else:
        st.caption("No calls yet.")