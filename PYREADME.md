# PyRuntime — Python API Reference

`PyRuntime` is the Python-facing async interface to the **SoulEngine** Rust core. It is exposed via a PyO3 extension module (`soulengine`) and manages the full lifecycle of users, agents, topic threads, and message memory.

---

## Installation & Import

```python
from soulengine import PyRuntime
```

> **Note:** The `soulengine` extension module requires a compatible build of the Rust core. On Windows, ensure `torch`'s DLL directory is added before importing if you are using torch-backed models.

```python
import torch, os
os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
from soulengine import PyRuntime
```

---

## Initialisation

### `PyRuntime.create(bind="127.0.0.1:3077")` → `PyRuntime`

Creates and returns a new `PyRuntime` instance. This is the **only** constructor — do not call `PyRuntime()` directly.
Also this launches the api server of the runtime
```python
runtime = await PyRuntime.create(bind="127.0.0.1:3077")
```

This is a `staticmethod` and must be awaited. It initialises the internal Rust `Runtime` and wraps it in an async-safe `Arc<RwLock<>>`.

---

## User Management

### `create_user(user_name: str)` → `str`

Registers a new user identity within the runtime and returns a unique `user_id`.

```python
user_id = await runtime.create_user("kattalaiUser")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_name` | `str` | Display name for the user |

**Returns:** `str` — opaque user ID, used in `insert_message`.

---

## Topic Threads

A **topic thread** is the shared conversation context that users and agents write to and read from.

### `create_topic_thread()` → `str`

Creates a new topic thread and returns its `topic_id`.

```python
topic_id = await runtime.create_topic_thread()
```

**Returns:** `str` — opaque topic ID.

---

### `topic_history_len(topic_id: str)` → `int`

Returns the total number of messages currently in the topic thread.

```python
length = await runtime.topic_history_len(topic_id)
```

Useful for polling — compare the value before and after a `insert_message` call to detect new activity.

---

### `iter_topic(topic_id: str, start_index: int)` → `str` (JSON)

Returns a JSON-serialised list of messages starting from `start_index`.

```python
raw = await runtime.iter_topic(topic_id, cursor)
entries = json.loads(raw)   # list of dicts
```

Each entry dict contains:

| Key | Type | Description |
|-----|------|-------------|
| `name` | `str` | Source name (agent name or user handle) |
| `role` | `str` | `"user"` or `"assistant"` |
| `content` | `str` | Raw message text (may contain block markers) |

**Tip:** Track a `cursor` integer and pass it as `start_index` to fetch only new messages since the last poll:

```python
cursor = await runtime.topic_history_len(topic_id)
# ... wait for activity ...
new_raw = await runtime.iter_topic(topic_id, cursor)
new_entries = json.loads(new_raw)
```

---

### `insert_message(topic_id: str, user_id: str, message: str)` → `str`

Inserts a user message into the topic thread. This triggers any agents currently attached to the topic to begin processing.

```python
await runtime.insert_message(topic_id, user_id, "Summarise my unread emails")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `topic_id` | `str` | Target topic thread |
| `user_id` | `str` | Sender identity (from `create_user`) |
| `message` | `str` | Message text |

**Returns:** `str` — confirmation value from the Rust layer.  
**Raises:** `ValueError` if the insert fails.

---

## Agent Management

### `get_agent_list()` → `list[str]`

Returns the list of agent names registered in the runtime's configuration.

```python
agents = await runtime.get_agent_list()
# e.g. ["Researcher", "Coder", "Writer"]
```

---

### `deploy_agent(agent_name: str)` → `str`

Deploys a named agent from the config registry and returns its `agent_id`.

```python
agent_id = await runtime.deploy_agent("Researcher")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_name` | `str` | Must match a name in `get_agent_list()` |

**Returns:** `str` — opaque agent ID used in topic and episode calls.

---

### `add_agent_to_topic(topic_id: str, agent_id: str)` → `str`

Attaches a deployed agent to a topic thread. The agent will start responding to new messages inserted into that topic.

```python
await runtime.add_agent_to_topic(topic_id, agent_id)
```

**Returns:** `str` — confirmation message.  
**Raises:** `ValueError` on failure.

> Only one agent should be active on a topic at a time in typical usage. Call `remove_agent_from_topic` before switching agents.

---

### `remove_agent_from_topic(topic_id: str, agent_id: str)` → `str`

Detaches an agent from a topic thread.

```python
await runtime.remove_agent_from_topic(topic_id, agent_id)
```

**Returns:** `str` — confirmation message.  
**Raises:** `ValueError` on failure.

---

### `is_agent_working_on_topic(topic_id: str, agent_id: str)` → `bool`

Returns `True` if the agent is currently processing a message on the given topic thread. Use this to drive a "thinking..." indicator in your UI.

```python
thinking = await runtime.is_agent_working_on_topic(topic_id, agent_id)
```

---

## Agent Episodes (Internal Memory)

An **episode** is the agent's internal working memory for a topic — its scratchpad of thoughts, tool calls, and intermediate outputs, separate from the shared topic history.

### `agent_episode_len(topic_id: str, agent_id: str)` → `int`

Returns the number of entries in the agent's episode memory for a given topic.

```python
ep_len = await runtime.agent_episode_len(topic_id, agent_id)
```

Use this alongside `iter_agent_episode` for incremental polling (same cursor pattern as `iter_topic`).

---

### `iter_agent_episode(topic_id: str, agent_id: str, start_index: int)` → `str` (JSON)

Returns a JSON-serialised list of the agent's internal episode entries from `start_index` onward.

```python
raw = await runtime.iter_agent_episode(topic_id, agent_id, cursor)
entries = json.loads(raw)
```

Each entry has the same shape as `iter_topic` entries (`name`, `role`, `content`). The `content` field typically contains structured response blocks (see **Block Format** below).

---

## Block Format

Agent message content uses a fenced block convention that the UI layer parses:

````
```thoughts
Agent reasoning goes here...
```

```terminal
tool_call(arg="value")
-> result
```

```output
Final response to the user.
```

```validation
Cross-check notes here.
```

```followup_context
Handoff state for the next turn.
```
````

A regex parser extracts these blocks for display:

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

## Configuration — Required TOML Files

`PyRuntime.create()` reads two TOML files at startup. Both must exist and be valid before calling the constructor or it will fail to initialise. If you installed from PyPI, run `kattalai-setup` once then `kattalai-folder` to open the directory where these files live. If you built from source, they are already present at `./configs/` in the repo root.

```
configs/
├── inference_config.toml   ← LLM provider credentials & settings
└── agents_config.toml      ← Agent definitions (name, goal, models, apps)
```

---

### `configs/inference_config.toml`

Defines one or more LLM providers. The runtime reads this to know which inference backends are available. You only need to fill in the providers you actually intend to use — unused blocks can be left out or left with empty API keys.

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

**Supported `inference_provider` values** (referenced in `agents_config.toml`):

| Value | Notes |
|-------|-------|
| `ollama` | Local inference, no API key needed. Requires Ollama running on `localhost:11434`. |
| `gemini` | Google Gemini API. Requires `api_key`. |
| `huggingface` | HuggingFace Inference Router. Requires `api_key`. |
| `sarvam` | Sarvam AI API. Requires `api_key`. |

**Minimum setup (local-only, no API keys):** Install Ollama, pull a model, and only include `[[ollama_config]]`:

```bash
ollama pull qwen3:4b    # reasoning model
ollama pull qwen3:0.6b  # lightweight NLP model
```

```toml
[[ollama_config]]
chat_api_url     = "http://localhost:11434/api/chat"
generate_api_url = "http://localhost:11434/api/generate"
temperature      = 0.1
```

---

### `configs/agents_config.toml`

Defines the agents that `deploy_agent(agent_name)` can load. Each `[[agent_config]]` block creates one deployable agent. The `agent_name` field here is exactly what you pass to `deploy_agent()` and what `get_agent_list()` returns.

```toml
[[agent_config]]
agent_name = "DIA"
agent_goal = "To assist user with their queries"
backstory  = "You are an AI assistant"

# Primary model — used for multi-step reasoning and planning
reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }

# Lightweight model — used for fast NLP classification and tool routing
nlp_model = { inference_provider = "ollama", model_id = "qwen3:0.6b" }

# Apps available to this agent at deploy time
default_apps = ["clock_app"]
```

**Key fields:**

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | `str` | Must match the name passed to `deploy_agent()` |
| `agent_goal` | `str` | Injected into the agent's system prompt as its objective |
| `backstory` | `str` | Additional persona context in the system prompt |
| `reasoning_model` | inline table | Provider + model ID for the main thinking loop |
| `nlp_model` | inline table | Provider + model ID for fast NLP/routing decisions |
| `default_apps` | `list[str]` | App handle names loaded on deploy (must match `app_handle_name` in app TOMLs) |

**Mixing providers per agent** is supported — e.g. Gemini for reasoning and Ollama for NLP:

```toml
reasoning_model = { inference_provider = "gemini",  model_id = "gemini-2.5-flash" }
nlp_model       = { inference_provider = "ollama",  model_id = "qwen3:0.6b" }
```

**Multiple agents** — add more `[[agent_config]]` blocks. All defined agents show up in `get_agent_list()`:

```toml
[[agent_config]]
agent_name      = "Researcher"
agent_goal      = "Research topics thoroughly and summarise findings"
backstory       = "You are a careful research assistant"
reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
default_apps    = ["grep_app", "notes_app"]

[[agent_config]]
agent_name      = "Coder"
agent_goal      = "Write and debug Python code"
backstory       = "You are a senior software engineer"
reasoning_model = { inference_provider = "gemini", model_id = "gemini-2.5-flash" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
default_apps    = ["calculator_app", "grep_app"]
```

---

### App TOML Schema (for `default_apps`)

Each app listed in `default_apps` must have a corresponding TOML file under `apps/`. The runtime auto-discovers all `*.toml` files under `./apps/` at startup — no registration step needed. The `app_handle_name` in the app TOML is the string you reference in `default_apps`.

```toml
app_name          = "Clock App"
app_path          = "./apps/core_apps/clock_app/clock_app.py"
app_start_command = "python"
app_start_args    = "./apps/core_apps/clock_app/clock_app.py"
app_handle_name   = "clock_app"       # ← this string goes in default_apps
app_launch_mode   = "REPL"            # "REPL" (persistent) or "ONE_SHOT"

app_usage_guideline = """
Use this app to get the current time or set timed reminders.
"""

[[app_command_signatures]]
command  = "get_time"
consumes = []
produces = ["current_time"]
action   = "read"

[[app_command_signatures]]
command  = "set_alarm"
consumes = ["duration", "label"]
produces = ["alarm_confirmation"]
action   = "write"
```

**Built-in app handles** (available after `kattalai-setup`):

| `app_handle_name` | Description |
|---|---|
| `clock_app` | Current time and timed alarms |
| `notes_app` | Note creation, search, and backup |
| `grep_app` | Regex/literal file search |
| `calculator_app` | Arithmetic and expression evaluation |
| `stock_tracker` | Live quotes and watchlists via `yfinance` |
| `webpage_reader` | Web page extraction via Playwright |

---

### Configuration → `PyRuntime` relationship

The diagram below shows exactly which config values feed into which `PyRuntime` calls:

```
inference_config.toml                agents_config.toml
─────────────────────                ──────────────────
[[ollama_config]]           ┐        agent_name  ──────────── deploy_agent("DIA")
[[gemini_config]]           ├──────► reasoning_model          get_agent_list() → ["DIA", ...]
[[huggingface_config]]      │        nlp_model
[[sarvam_config]]           ┘        default_apps ─────────── app TOMLs in ./apps/
                                     │
                                     └── agent_goal  ─────── system prompt (internal)
                                         backstory   ─────── system prompt (internal)
```

Both files are read once inside `PyRuntime.create()`. Changing them requires restarting the runtime — there is no hot-reload.

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

    # 3. Send a message and poll for reply
    cursor = await runtime.topic_history_len(topic_id)
    await runtime.insert_message(topic_id, user_id, "Hello!")

    while True:
        await asyncio.sleep(0.5)
        new_len = await runtime.topic_history_len(topic_id)
        if new_len > cursor:
            break

    # 4. Fetch new messages
    entries = json.loads(await runtime.iter_topic(topic_id, cursor))
    for entry in entries:
        if entry["role"] != "user":
            print(f"{entry['name']}: {entry['content']}")

asyncio.run(main())
```

---

## Error Handling

All `PyRuntime` methods raise `ValueError` on internal Rust errors. Wrap calls in `try/except`:

```python
try:
    await runtime.insert_message(topic_id, user_id, text)
except ValueError as e:
    print(f"SoulEngine error: {e}")
```

---

## Thread Safety Notes

- The Rust runtime uses `Arc<RwLock<Runtime>>` internally.
- `create`, `deploy_agent`, `create_user`, `create_topic_thread` acquire a **write** lock.
- `insert_message`, `iter_topic`, `topic_history_len`, and all read operations acquire a **read** lock.
- All methods are `async` — use with `asyncio` or an async framework like `textual`.

---

## Writing a New App

Apps are the tools agents use to act in the world. Each app is a self-contained Python script paired with a TOML config. The runtime discovers apps automatically — there is no registration step. Drop a folder with a `.py` + `.toml` pair under `apps/` and it will be available to any agent whose `default_apps` list references its handle.

Run `kattalai-folder` to open the install directory, then navigate to `apps/` to see the existing core apps as reference implementations.

---

### Step 1 — Create the folder

```
apps/
└── core_apps/              # or other_apps/ for optional/experimental apps
    └── my_new_app/
        ├── my_new_app.py   # the app script
        └── my_new_app.toml # the capability config
```

Both files must sit in the same folder. The folder name, script name, and TOML name do not need to match each other, but it is conventional to keep them consistent.

---

### Step 2 — Write the TOML config

The TOML config is what the runtime embeds and uses for tool routing. Write it carefully — the `app_usage_guideline` text is the primary signal the agent uses to decide *when* to invoke this app.

```toml
app_name          = "Weather App"
app_path          = "./apps/core_apps/weather_app/weather_app.py"
app_start_command = "python"
app_start_args    = "./apps/core_apps/weather_app/weather_app.py"
app_handle_name   = "weather_app"    # unique handle — used in default_apps and agent commands
app_launch_mode   = "REPL"           # "REPL" or "ONE_SHOT" — see below

app_usage_guideline = """
Use this app to get current weather conditions or forecasts for any city.
Invoke when the user asks about weather, temperature, rain, or climate.
"""

[[app_command_signatures]]
command  = "current"
consumes = ["city_name"]
produces = ["temperature", "conditions", "humidity"]
action   = "read"

[[app_command_signatures]]
command  = "forecast"
consumes = ["city_name", "days"]
produces = ["forecast_list"]
action   = "read"
```

**Field reference:**

| Field | Required | Description |
|-------|----------|-------------|
| `app_name` | ✓ | Human-readable display name |
| `app_path` | ✓ | Path to the Python script, relative to the runtime working directory |
| `app_start_command` | ✓ | Interpreter — almost always `"python"` |
| `app_start_args` | ✓ | Arguments passed to `app_start_command` — typically same as `app_path` |
| `app_handle_name` | ✓ | Unique short identifier. Must be a valid identifier string with no spaces. Referenced in `default_apps` and in agent commands as `&<handle_name>` |
| `app_launch_mode` | ✓ | `"REPL"` — process is started once and kept alive. `"ONE_SHOT"` — process is spawned fresh per invocation |
| `app_usage_guideline` | ✓ | Free text description embedded by the runtime. This is the primary signal for semantic app selection — be specific about *when* to use the app |
| `[[app_command_signatures]]` | ✓ (≥1) | One block per command the app accepts |
| `command` | ✓ | Command name string — must match what the Python script expects |
| `consumes` | ✓ | Input type names (can be empty list `[]`) |
| `produces` | ✓ | Output type names |
| `action` | ✓ | 1–2 word verb describing the operation: `read`, `write`, `compute`, `search`, `fetch`, `send`, `delete` |

**`app_launch_mode` guidance:**

| Mode | When to use |
|------|-------------|
| `REPL` | App maintains state between calls (e.g. clock alarms, open file handles, cached data). The process stays running and listens for repeated commands on stdin. |
| `ONE_SHOT` | App is stateless or each call is independent (e.g. notes lookup, single calculation). A fresh Python process is spawned per invocation. |

---

### Step 3 — Write the Python script

The script communicates with the Rust terminal layer through a structured message protocol on stdin/stdout. The `soul_engine_app` helper from `se_app_utils` manages the REPL loop and protocol framing for you.

**Import pattern:**

```python
import json
import sys
import asyncio
from pathlib import Path

# Walk up to the apps/ root so se_app_utils is importable
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))

import se_app_utils
from se_app_utils.soulengine import soul_engine_app
```

> `Path(__file__).resolve().parent.parent.parent` assumes the script is three levels deep under `apps/` (e.g. `apps/core_apps/my_app/my_app.py`). Adjust `.parent` count if your layout differs.

**Minimal REPL app skeleton:**

```python
import json
import sys
import asyncio
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


async def process_command(se_interface, args):
    """
    Called by soul_engine_app for every inbound invocation.

    Args:
        se_interface  – messaging handle; call se_interface.send_message(json_str) to reply
        args          – list of string tokens from the agent's command invocation;
                        args[0] is typically the subcommand, args[1:] are parameters
    """
    if not args:
        se_interface.send_message(json.dumps({
            "status": "error",
            "message": "No command provided"
        }))
        return

    command = args[0]

    if command == "current":
        city = args[1] if len(args) > 1 else "unknown"
        # Replace with real implementation
        se_interface.send_message(json.dumps({
            "status": "ok",
            "city": city,
            "temperature": "28°C",
            "conditions": "partly cloudy",
            "humidity": "65%"
        }))

    elif command == "forecast":
        city = args[1] if len(args) > 1 else "unknown"
        se_interface.send_message(json.dumps({
            "status": "ok",
            "city": city,
            "forecast": ["Mon 28°C", "Tue 27°C", "Wed 29°C"]
        }))

    else:
        se_interface.send_message(json.dumps({
            "status": "error",
            "message": f"Unknown command: {command}"
        }))


if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="Weather App")
    soul_app.run_repl(main_fn=process_command)
```

**What `soul_engine_app` does for you:**

- Reads JSON-encoded commands from stdin in the format the Rust terminal layer sends.
- Calls your `process_command(se_interface, args)` coroutine with a messaging handle and the parsed argument list.
- Keeps the process alive in a loop for `REPL` mode.
- `se_interface.send_message(json_str)` writes the response back to stdout wrapped in the `[#APP_MESSAGE>...]` protocol markers that the Rust layer reads.

**Protocol message format (for reference — handled by `soul_engine_app` automatically):**

```
# Inbound (Rust → Python, on stdin):
[#APP_INVOKE>{"command": "current", "args": ["Chennai"]}]

# Outbound (Python → Rust, on stdout):
[#APP_MESSAGE>{"status": "ok", "temperature": "32°C", "conditions": "sunny"}]
```

You only need to interact with the protocol directly if you are not using `soul_engine_app`.

**Async support:** `process_command` is an `async def` — you can `await asyncio.sleep(...)` or any other coroutine inside it. This is particularly useful for timer-based apps that need to send an acknowledgement, wait, then fire a follow-up message:

```python
async def process_command(se_interface, args):
    # ... parse and validate args ...

    # Send acknowledgement immediately
    se_interface.send_message(json.dumps({
        "status": "alarm_set",
        "fires_at": target_str,
        "message": alarm_msg
    }))

    await asyncio.sleep(seconds)   # non-blocking wait

    # Fire the follow-up after the delay
    se_interface.send_message(json.dumps({
        "status": "alarm_fired",
        "message": alarm_msg
    }))
```

---

### Step 4 — Register the handle in `agents_config.toml`

Add your new `app_handle_name` to the `default_apps` list of any agent that should have access to it:

```toml
[[agent_config]]
agent_name   = "DIA"
agent_goal   = "To assist user with their queries"
backstory    = "You are an AI assistant"
reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
default_apps = ["clock_app", "notes_app", "weather_app"]   # ← add here
```

The `app_handle_name` in the TOML and the string in `default_apps` must match exactly.

---

### Step 5 — Verify discovery

Restart the runtime and check the Logs tab (or `cargo run --release` output) for a line like:

```
[appstore] loaded: weather_app  (REPL)  commands: current, forecast
```

If the app does not appear, common causes are:

- The TOML file is not under the `./apps/` directory tree.
- `app_handle_name` contains spaces or special characters.
- A syntax error in the TOML — run `python -c "import tomllib; tomllib.load(open('my_new_app.toml','rb'))"` to validate.
- The `app_path` is wrong relative to the runtime working directory (always the repo/install root, not the app folder).

---

### Complete working example — `calculator_app`

This is one of the built-in core apps and is a good reference for a minimal correct implementation.

**`apps/core_apps/calculator_app/calculator_app.toml`:**

```toml
app_name          = "Calculator App"
app_path          = "./apps/core_apps/calculator_app/calculator_app.py"
app_start_command = "python"
app_start_args    = "./apps/core_apps/calculator_app/calculator_app.py"
app_handle_name   = "calculator_app"
app_launch_mode   = "REPL"

app_usage_guideline = """
Use this app for arithmetic calculations, expression evaluation, and storing
named variables for reuse across computations. Invoke when the user asks to
calculate, compute, evaluate an expression, or do maths.
"""

[[app_command_signatures]]
command  = "calculate"
consumes = ["expression"]
produces = ["result"]
action   = "compute"

[[app_command_signatures]]
command  = "store"
consumes = ["variable_name", "value"]
produces = ["confirmation"]
action   = "write"

[[app_command_signatures]]
command  = "recall"
consumes = ["variable_name"]
produces = ["value"]
action   = "read"
```

**`apps/core_apps/calculator_app/calculator_app.py`:**

```python
import json
import sys
import asyncio
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

_vars: dict = {}   # persistent variable store across REPL calls


async def process_command(se_interface, args):
    """
    Commands:
      calculate <expression>         → evaluate expression (may reference stored vars)
      store <variable_name> <value>  → store a named variable
      recall <variable_name>         → retrieve a stored variable
    """
    if not args:
        se_interface.send_message(json.dumps({
            "status": "error",
            "message": "No command provided. Use: calculate | store | recall"
        }))
        return

    command = args[0]

    if command == "calculate":
        expr = " ".join(args[1:]).strip()
        if not expr:
            se_interface.send_message(json.dumps({
                "status": "error",
                "message": "No expression provided."
            }))
            return
        try:
            result = eval(expr, {"__builtins__": {}}, _vars)
            se_interface.send_message(json.dumps({
                "status": "ok",
                "expression": expr,
                "result": result
            }))
        except Exception as e:
            se_interface.send_message(json.dumps({
                "status": "error",
                "message": str(e)
            }))

    elif command == "store":
        if len(args) < 3:
            se_interface.send_message(json.dumps({
                "status": "error",
                "message": "Usage: store <variable_name> <value>"
            }))
            return
        name  = args[1]
        value = args[2]
        try:
            _vars[name] = eval(value, {"__builtins__": {}}, _vars)
        except Exception:
            _vars[name] = value   # store as string if eval fails
        se_interface.send_message(json.dumps({
            "status": "ok",
            "stored": name,
            "value": _vars[name]
        }))

    elif command == "recall":
        if len(args) < 2:
            se_interface.send_message(json.dumps({
                "status": "error",
                "message": "Usage: recall <variable_name>"
            }))
            return
        name = args[1]
        if name in _vars:
            se_interface.send_message(json.dumps({
                "status": "ok",
                "variable": name,
                "value": _vars[name]
            }))
        else:
            se_interface.send_message(json.dumps({
                "status": "error",
                "message": f"Variable '{name}' not found."
            }))

    else:
        se_interface.send_message(json.dumps({
            "status": "error",
            "message": f"Unknown command: {command}"
        }))


if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="Calculator App")
    soul_app.run_repl(main_fn=process_command)
```

---

### App authoring checklist

Before testing your new app end-to-end with the runtime:

- [ ] Folder created under `apps/core_apps/` or `apps/other_apps/`
- [ ] TOML has unique `app_handle_name` with no spaces
- [ ] `app_path` is relative to the **runtime working directory** (repo/install root), not to the app folder
- [ ] `app_usage_guideline` clearly describes *when* to use the app — this is embedded for semantic search
- [ ] At least one `[[app_command_signatures]]` block defined
- [ ] Python script resolves `apps_path` via `Path(__file__).resolve().parent.parent.parent` and appends it to `sys.path`
- [ ] Python script imports `soul_engine_app` from `se_app_utils.soulengine`
- [ ] Entry point is `async def process_command(se_interface, args)` — all replies via `se_interface.send_message(json.dumps({...}))`
- [ ] Script bottom is `soul_engine_app(app_name="...").run_repl(main_fn=process_command)`
- [ ] `app_handle_name` added to `default_apps` in `agents_config.toml` for the relevant agent
- [ ] Restart runtime and confirm the app appears in Logs tab