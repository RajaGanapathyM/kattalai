# PyRuntime — Python API Reference

`PyRuntime` is the Python-facing async interface to the **soulengine** Rust core. Exposed via a PyO3 extension module, it manages the full lifecycle of users, agents, topic threads, and message memory.

---

## Contents

- [Installation & Import](#installation--import)
- [Initialisation](#initialisation)
- [User Management](#user-management)
- [Topic Threads](#topic-threads)
- [Agent Management](#agent-management)
- [Agent Episodes](#agent-episodes-internal-memory)
- [Block Format](#block-format)
- [Configuration Reference](#configuration-reference)
  - [inference\_config.toml](#inference_configtoml)
  - [agents\_config.toml](#agents_configtoml)
  - [App TOML Schema](#app-toml-schema)
- [Typical Usage Pattern](#typical-usage-pattern)
- [Error Handling](#error-handling)
- [Thread Safety](#thread-safety)

---

## Installation & Import

```python
from soulengine import PyRuntime
```

> **Windows:** Ensure PyTorch's DLL directory is added before importing.

```python
import torch, os
os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
from soulengine import PyRuntime
```

---

## Initialisation

### `PyRuntime.create(bind="127.0.0.1:3077")` → `PyRuntime`

Creates and returns a new `PyRuntime` instance. This is the **only constructor** — do not call `PyRuntime()` directly. Also launches the HTTP API server at the given bind address.

```python
runtime = await PyRuntime.create(bind="127.0.0.1:3077")
```

This is a `staticmethod` and must be `await`ed. It initialises the internal Rust `Runtime` wrapped in `Arc<RwLock<>>`.

Reads two config files at startup — both must exist and be valid:

```
configs/
├── inference_config.toml
└── agents_config.toml
```

---

## User Management

### `create_user(user_name: str)` → `str`

Registers a new user identity and returns a unique `user_id`.

```python
user_id = await runtime.create_user("kattalaiUser")
```

| Parameter | Type | Description |
|---|---|---|
| `user_name` | `str` | Display name for the user |

**Returns:** `str` — opaque user ID, required for `insert_message`.

---

## Topic Threads

A **topic thread** is the shared conversation context that users and agents read from and write to.

### `create_topic_thread()` → `str`

Creates a new topic thread and returns its `topic_id`.

```python
topic_id = await runtime.create_topic_thread()
```

---

### `topic_history_len(topic_id: str)` → `int`

Returns the total number of messages in the thread. Use this for polling — compare before and after `insert_message` to detect new activity.

```python
length = await runtime.topic_history_len(topic_id)
```

---

### `iter_topic(topic_id: str, start_index: int)` → `str` (JSON)

Returns a JSON-serialised list of messages from `start_index` onward.

```python
raw     = await runtime.iter_topic(topic_id, cursor)
entries = json.loads(raw)   # list of dicts
```

Each entry contains:

| Key | Type | Description |
|---|---|---|
| `name` | `str` | Source name (agent name or user handle) |
| `role` | `str` | `"user"` or `"assistant"` |
| `content` | `str` | Raw message text (may contain block markers) |

**Incremental polling pattern:**

```python
# Snapshot length before sending
cursor = await runtime.topic_history_len(topic_id)

# ... send message, wait ...

# Fetch only new entries
new_entries = json.loads(await runtime.iter_topic(topic_id, cursor))
```

---

### `insert_message(topic_id: str, user_id: str, message: str)` → `str`

Inserts a user message into the thread. This triggers attached agents to begin processing.

```python
await runtime.insert_message(topic_id, user_id, "Summarise my unread emails")
```

| Parameter | Type | Description |
|---|---|---|
| `topic_id` | `str` | Target topic thread |
| `user_id` | `str` | Sender identity (from `create_user`) |
| `message` | `str` | Message text |

**Returns:** `str` — confirmation from the Rust layer.  
**Raises:** `ValueError` if the insert fails.

---

## Agent Management

### `get_agent_list()` → `list[str]`

Returns the list of agent names registered in the config.

```python
agents = await runtime.get_agent_list()
# e.g. ["Researcher", "Coder", "DIA"]
```

---

### `deploy_agent(agent_name: str)` → `str`

Deploys a named agent and returns its `agent_id`.

```python
agent_id = await runtime.deploy_agent("Researcher")
```

| Parameter | Type | Description |
|---|---|---|
| `agent_name` | `str` | Must match a name in `get_agent_list()` |

**Returns:** `str` — opaque agent ID used in topic and episode calls.

---

### `add_agent_to_topic(topic_id: str, agent_id: str)` → `str`

Attaches an agent to a topic thread. The agent begins responding to new messages inserted into that topic.

```python
await runtime.add_agent_to_topic(topic_id, agent_id)
```

> Only one agent should be active on a topic at a time. Call `remove_agent_from_topic` before switching agents.

**Returns:** `str` — confirmation. **Raises:** `ValueError` on failure.

---

### `remove_agent_from_topic(topic_id: str, agent_id: str)` → `str`

Detaches an agent from a topic thread.

```python
await runtime.remove_agent_from_topic(topic_id, agent_id)
```

**Returns:** `str` — confirmation. **Raises:** `ValueError` on failure.

---

### `is_agent_working_on_topic(topic_id: str, agent_id: str)` → `bool`

Returns `True` if the agent is currently processing a message. Use this to drive a "thinking…" indicator.

```python
thinking = await runtime.is_agent_working_on_topic(topic_id, agent_id)
```

---

## Agent Episodes (Internal Memory)

An **episode** is the agent's internal working scratchpad for a topic — thoughts, tool calls, and intermediate outputs, separate from the shared topic history.

### `agent_episode_len(topic_id: str, agent_id: str)` → `int`

Returns the number of entries in the agent's episode memory.

```python
ep_len = await runtime.agent_episode_len(topic_id, agent_id)
```

---

### `iter_agent_episode(topic_id: str, agent_id: str, start_index: int)` → `str` (JSON)

Returns a JSON-serialised list of the agent's internal episode entries from `start_index` onward. Same shape as `iter_topic` entries (`name`, `role`, `content`). The `content` field contains structured response blocks.

```python
raw     = await runtime.iter_agent_episode(topic_id, agent_id, cursor)
entries = json.loads(raw)
```

---

## Block Format

Agent `content` fields use fenced-block conventions that the UI layer parses:

````markdown
```thoughts
Agent reasoning goes here...
```

```terminal
&app_handle command arg
-> result
```

```output
Final response to the user.
```

```validation
Cross-check notes.
```

```followup_context
Handoff state for the next turn.
```
````

**Parser:**

```python
import re

def parse_se_content(content: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'```(thoughts|terminal|output|validation|followup_context)\s*\n(.*?)```',
        re.DOTALL
    )
    matches = pattern.findall(content)
    if matches:
        return [(kind.strip(), body.strip()) for kind, body in matches if body.strip()]
    return [("output", content.strip())]  # plain-text fallback
```

---

## Configuration Reference

Both files are read once inside `PyRuntime.create()`. Changes require a runtime restart — there is no hot-reload.

### `inference_config.toml`

```toml
[[ollama_config]]
chat_api_url     = "http://localhost:11434/api/chat"
generate_api_url = "http://localhost:11434/api/generate"
temperature      = 0.1

[[gemini_config]]
api_key     = "YOUR_GEMINI_API_KEY"
temperature = 0.1

[[huggingface_config]]
api_key        = "YOUR_HF_API_KEY"
max_new_tokens = 8000
temperature    = 0.1

[[sarvam_config]]
api_key          = "YOUR_SARVAM_API_KEY"
max_new_tokens   = 8000
temperature      = 0.1
reasoning_effort = "high"
```

| `inference_provider` | Notes |
|---|---|
| `ollama` | Local inference, no API key. Requires Ollama on `localhost:11434`. |
| `gemini` | Google Gemini API. Requires `api_key`. |
| `huggingface` | HuggingFace Inference Router. Requires `api_key`. |
| `sarvam` | Sarvam AI API. Requires `api_key`. |

**Minimum local-only config:**

```toml
[[ollama_config]]
chat_api_url     = "http://localhost:11434/api/chat"
generate_api_url = "http://localhost:11434/api/generate"
temperature      = 0.1
```

---

### `agents_config.toml`

```toml
[[agent_config]]
agent_name = "DIA"
agent_goal = "To assist user with their queries"
backstory  = "You are an AI assistant"

reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
default_apps    = ["clock_app"]
```

| Field | Type | Description |
|---|---|---|
| `agent_name` | `str` | Name passed to `deploy_agent()` and returned by `get_agent_list()` |
| `agent_goal` | `str` | Injected into the agent's system prompt as its objective |
| `backstory` | `str` | Additional persona context in the system prompt |
| `reasoning_model` | inline table | Provider + model ID for the main thinking loop |
| `nlp_model` | inline table | Provider + model ID for fast NLP/routing decisions |
| `default_apps` | `list[str]` | App handles loaded on deploy — must match `app_handle_name` in app TOMLs |

**Mixing providers per agent:**

```toml
reasoning_model = { inference_provider = "gemini", model_id = "gemini-2.5-flash" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
```

---

### App TOML Schema

The `app_handle_name` in an app's TOML is the string referenced in `default_apps`.

```toml
app_name          = "Clock App"
app_path          = "./apps/core_apps/clock_app/clock_app.py"
app_start_command = "python"
app_start_args    = "./apps/core_apps/clock_app/clock_app.py"
app_handle_name   = "clock_app"
app_launch_mode   = "REPL"

app_usage_guideline = """
Use to get the current time or set timed reminders.
"""

[[app_command_signatures]]
command  = "get_time"
consumes = []
produces = ["current_time"]
action   = "read"
```

**Built-in handle names** (available after `kattalai-setup`):

| Handle | Description |
|---|---|
| `clock_app` | Current time and alarms |
| `notes_app` | Note CRUD and search |
| `grep_app` | File and stdin search |
| `calculator_app` | Arithmetic and variables |
| `stock_tracker` | Live quotes via yfinance |
| `webpage_reader` | Web extraction via Playwright |

---

## Typical Usage Pattern

```python
import asyncio, json
from soulengine import PyRuntime

async def main():
    # 1. Bootstrap
    runtime  = await PyRuntime.create()
    user_id  = await runtime.create_user("alice")
    topic_id = await runtime.create_topic_thread()

    # 2. Deploy and attach an agent
    agents   = await runtime.get_agent_list()
    agent_id = await runtime.deploy_agent(agents[0])
    await runtime.add_agent_to_topic(topic_id, agent_id)

    # 3. Snapshot cursor, send message
    cursor = await runtime.topic_history_len(topic_id)
    await runtime.insert_message(topic_id, user_id, "Hello!")

    # 4. Poll until the agent finishes
    while await runtime.is_agent_working_on_topic(topic_id, agent_id):
        await asyncio.sleep(0.5)

    # 5. Fetch new messages
    entries = json.loads(await runtime.iter_topic(topic_id, cursor))
    for entry in entries:
        if entry["role"] != "user":
            print(f"{entry['name']}: {entry['content']}")

asyncio.run(main())
```

---

## Error Handling

All `PyRuntime` methods raise `ValueError` on internal Rust errors.

```python
try:
    await runtime.insert_message(topic_id, user_id, text)
except ValueError as e:
    print(f"SoulEngine error: {e}")
```

---

## Thread Safety

The Rust runtime uses `Arc<RwLock<Runtime>>` internally.

| Operations | Lock type |
|---|---|
| `create`, `deploy_agent`, `create_user`, `create_topic_thread` | Write lock |
| `insert_message`, `iter_topic`, `topic_history_len`, all reads | Read lock |

All methods are `async` — use with `asyncio` or an async framework like `textual`. Do not share a `PyRuntime` instance across threads without an async executor.
