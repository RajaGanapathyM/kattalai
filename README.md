<div align="center">

# கட்டளை · kattalai

**An AI agent runtime that orchestrates Python apps to act as your coworker.**

[![PyPI](https://img.shields.io/pypi/v/kattalai?color=0a0a0a&style=flat-square)](https://pypi.org/project/kattalai/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square)](LICENSE)
[![WhatsApp Community](https://img.shields.io/badge/community-WhatsApp-25D366?style=flat-square&logo=whatsapp)](https://chat.whatsapp.com/GpOBwFIloGE93LV7prsoxS?mode=gi_t)

*கட்டளை (Tamil) — "command" or "obligation"*

</div>

---

**kattalai** sits between a user and the operating system. Instead of exposing raw commands, it routes natural-language intent to focused Python utility apps — each defined by a TOML config — using LLM reasoning, NLP classification, and embedding-based semantic search.

Think of it like giving Claude a set of Python tools and letting it figure out when and how to use them.

```
User intent  →  LLM reasoning  →  App selection  →  Python app  →  Result
```

**Core architecture:**
- **`soulengine`** — Rust core. Handles agent lifecycle, memory, inference, app discovery, and tool routing. Compiled as a Python extension via PyO3/maturin.
- **`kattalai.py`** — Textual TUI frontend. Drives `PyRuntime` to present a chat/agent interface.
- **Apps** — Self-contained Python scripts + TOML configs. Drop one in `apps/` and it's automatically discovered.

---
![kattalai banner](assets/banner_img_kattalai.png)
---
<div align="center">

**[PyPI](https://pypi.org/project/kattalai/)** · **[HTTP API](API-Readme.md)** · **[Python API](PYREADME.md)** · **[WhatsApp Community](https://chat.whatsapp.com/GpOBwFIloGE93LV7prsoxS?mode=gi_t)**

</div>

## Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [From PyPI](#from-pypi-recommended)
  - [From Source](#from-source)
- [Configuration](#configuration)
  - [inference\_config.toml](#inference_configtoml)
  - [agents\_config.toml](#agents_configtoml)
- [Running kattalai](#running-kattalai)
- [Apps System](#apps-system)
  - [Built-in Apps](#built-in-apps)
  - [App TOML Schema](#app-toml-schema)
  - [Writing a New App](#writing-a-new-app)
- [Prompts](#prompts)
- [Model Assets](#model-assets)
- [Repository Structure](#repository-structure)
- [License](#license)

---

## Quick Start

```bash
pip3 install kattalai
kattalai-setup    # download apps, configs, prompts, model assets
kattalai          # launch the TUI
```

> **API access** — once running, the runtime also exposes an HTTP API at `http://127.0.0.1:3077`. See the [HTTP API reference](API-Readme.md) for details.

---

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.9 – 3.13 | Required |
| Ollama | latest | For local inference without API keys |
| Rust + Cargo | ≥ 1.85 (edition 2024) | Source builds only |
| maturin | ≥ 1.x | Source builds only |

**Install Ollama (recommended for local-first setup):**

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen3:4b    # primary reasoning model
ollama pull qwen3:0.6b  # lightweight NLP/routing model
```

---

## Installation

### From PyPI (recommended)

```bash
pip3 install kattalai
```

> **⚠️ PATH warning (Windows):** If pip prints a warning that the `kattalai` script is not on PATH, copy the Scripts path from the warning and run:
> ```bash
> setx PATH "%PATH%;<paste Scripts path here>"
> ```
> Then open a new terminal.

**Run first-time setup** to download apps, configs, prompts, and model assets:

```bash
kattalai-setup
```

**Install remaining Python dependencies:**

```bash
pip3 install textual yfinance playwright
pip3 install "torch>=2.4.0" "numpy<2"

# Optional — required only for the webpage reader app
playwright install chromium
```

**Open the install folder** (to edit configs, apps, or prompts):

```bash
kattalai-folder
```

---

### From Source

```bash
git clone https://github.com/RajaGanapathyM/kattalai.git
cd kattalai

python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate.bat     # Windows

pip3 install maturin
maturin develop --release

pip3 install textual yfinance playwright
pip3 install "torch==2.4.0" "numpy<2"
playwright install chromium       # optional
```

> When building from source, `apps/`, `configs/`, `prompts/`, and `model_assets/` are already present in the repo — skip `kattalai-setup`.

> **Windows DLL note:** If you hit DLL loading errors at startup, ensure PyTorch is installed. `kattalai.py` adds its lib directory to the DLL search path automatically.

---

## Configuration

All config lives in `configs/`. Run `kattalai-folder` to open the install directory. Both files must exist before the runtime can start.

### `inference_config.toml`

Defines credentials and parameters for each LLM provider. Include only the providers you intend to use.

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

**Supported `inference_provider` values:** `ollama` · `gemini` · `huggingface` · `sarvam`

**Minimum setup (local, no API keys):** Include only `[[ollama_config]]` with Ollama running.

---

### `agents_config.toml`

Defines one or more deployable agents. Each `[[agent_config]]` block maps to a name you pass to `deploy_agent()`.

```toml
[[agent_config]]
agent_name = "DIA"
agent_goal = "To assist user with their queries"
backstory  = "You are an AI assistant"

reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }
nlp_model       = { inference_provider = "ollama", model_id = "qwen3:0.6b" }
default_apps    = ["clock_app"]
```

**Multiple agents and mixed providers are supported:**

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

## Running kattalai

**TUI frontend:**

```bash
kattalai
# or, from a source build:
python ./pysrc/soulengine/kattalai.py
```

The TUI has three tabs:

| Tab | Description |
|---|---|
| **Chat** | Send messages to the deployed agent. Responses appear as structured blocks: `thoughts` / `terminal` / `output`. |
| **Agent Thoughts** | Live view of the agent's internal reasoning episode for the current topic. |
| **Logs** | Raw terminal output from app subprocesses. |

**Rust binary (dev/testing):**

```bash
# From the repo root — do not run from inside src/
cargo run --release
```

This runs the same initialisation as the TUI (embedder → app store → inference store → agent store) and sends test messages. Useful for verifying your environment before launching the full TUI.

---

## Apps System

Apps are the tools agents use to act in the world. Each app is a Python script paired with a TOML config. The runtime auto-discovers every `*.toml` under `./apps/` at startup — no registration step needed.

Agents invoke apps using the pattern `&<handle_name> <command> [args]`.

### Built-in Apps

| Handle | Mode | Description |
|---|---|---|
| `clock_app` | REPL | Current time and timed alarms. `&clock_app 5m Coffee break` |
| `notes_app` | ONE_SHOT | Note creation, search, tagging, and backup. `&notes_app read --tag bug` |
| `grep_app` | REPL | Regex/literal file search with context, recursive walk, stdin. `&grep_app search "TODO" ./src` |
| `calculator_app` | REPL | Arithmetic, expression evaluation, persistent variable store. |
| `stock_tracker` | REPL | Live quotes, fundamentals, history, watchlist, price alerts via `yfinance`. NSE/BSE supported (`.NS`, `.BO`). |
| `webpage_reader` | REPL | Web page extraction via Playwright. Requires `playwright install chromium`. |

---

### App TOML Schema

```toml
app_name          = "Human-readable name"
app_path          = "./apps/core_apps/my_app/my_app.py"
app_start_command = "python"
app_start_args    = "./apps/core_apps/my_app/my_app.py"
app_handle_name   = "my_app"    # unique identifier — no spaces
app_launch_mode   = "REPL"      # "REPL" (persistent) or "ONE_SHOT" (per-invocation)

app_usage_guideline = """
Describe when and how to use this app. This text is embedded and
used by the agent for semantic app selection — be specific.
"""

[[app_command_signatures]]
command  = "command_name"
consumes = ["input_type"]
produces = ["output_type"]
action   = "read"               # 1–2 word verb: read, write, compute, search, fetch, send, delete
```

**`app_launch_mode` guidance:**

| Mode | When to use |
|---|---|
| `REPL` | App maintains state between calls (alarms, file handles, cached data). Process stays running and listens on stdin. |
| `ONE_SHOT` | Stateless or independent calls (lookups, single calculations). Fresh process per invocation. |

---

### Writing a New App

#### 1. Create the folder

```
apps/
└── core_apps/
    └── my_new_app/
        ├── my_new_app.py
        └── my_new_app.toml
```

#### 2. Write the TOML config

Follow the schema above. The `app_usage_guideline` is the primary signal the agent uses to decide when to invoke your app — write it clearly.

#### 3. Write the Python script

```python
import json
import sys
import asyncio
from pathlib import Path

# Resolve apps/ root so se_app_utils is importable
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))

import se_app_utils
from se_app_utils.soulengine import soul_engine_app


async def process_command(se_interface, args):
    """
    Called for every inbound invocation.
    args[0]  → subcommand
    args[1:] → parameters
    Reply via se_interface.send_message(json.dumps({...}))
    """
    if not args:
        se_interface.send_message(json.dumps({"status": "error", "message": "No command provided"}))
        return

    command = args[0]

    if command == "my_command":
        se_interface.send_message(json.dumps({"status": "ok", "result": "..."}))
    else:
        se_interface.send_message(json.dumps({"status": "error", "message": f"Unknown command: {command}"}))


if __name__ == "__main__":
    soul_engine_app(app_name="My App").run_repl(main_fn=process_command)
```

`soul_engine_app` handles the REPL loop, stdin parsing, and the `[#APP_MESSAGE>...]` / `[#APP_INVOKE>...]` protocol framing. You only need to implement `process_command`.

#### 4. Register in `agents_config.toml`

```toml
default_apps = ["clock_app", "notes_app", "my_app"]
```

#### 5. Verify discovery

Restart the runtime and look for:

```
[appstore] loaded: my_app  (REPL)  commands: my_command
```

**Common causes if the app doesn't appear:**

- TOML is not under the `./apps/` tree
- `app_handle_name` contains spaces or special characters
- `app_path` is relative to the wrong working directory (must be relative to the runtime root, not the app folder)
- TOML syntax error — validate with: `python -c "import tomllib; tomllib.load(open('my_app.toml','rb'))"`

#### App authoring checklist

- [ ] Folder under `apps/core_apps/` or `apps/other_apps/`
- [ ] `app_handle_name` is unique, no spaces
- [ ] `app_path` is relative to the **runtime working directory**
- [ ] `app_usage_guideline` clearly describes when to use the app
- [ ] At least one `[[app_command_signatures]]` block
- [ ] `sys.path.append` resolves to `apps/` root
- [ ] Entry point is `async def process_command(se_interface, args)`
- [ ] All replies via `se_interface.send_message(json.dumps({...}))`
- [ ] Bottom of script: `soul_engine_app(...).run_repl(main_fn=process_command)`
- [ ] Handle added to `default_apps` in `agents_config.toml`
- [ ] Runtime restarted; app visible in Logs tab

---

## Prompts

Prompt files in `prompts/` define agent reasoning behaviour. Loaded at runtime — edit and restart to apply changes, no recompile needed.

| File | Purpose |
|---|---|
| `AGENT_OPERATING_RULES.md` | Hard constraints and invariants |
| `AGENT_REASONING_PROMPT.md` | Base reasoning loop |
| `AGENT_RAC_PROMPT.md` | ReAct + Critique — think, act, critique cycle |
| `AGENT_TOT_PROMPT.md` | Tree of Thoughts — multi-branch exploration |
| `AGENT_RESPONSE_REPAIR_PROMPT.md` | Repair template for malformed structured responses |
| `CONTEXT_TAGGING_PROMPT.md` | Context labelling for multi-turn handoffs |

---

## Model Assets

| Asset | Location | Notes |
|---|---|---|
| nlprule POS tagger (en, de, es) | `model_assets/pos_model/` | Bundled in repo. Lightweight NLP classification without an LLM call. |
| BGE-small-en-v1.5 embeddings | `model_assets/bge-small-en-v1.5/` | Auto-downloaded on first run via `fastembed`. Subsequent starts are instant. |

**Air-gapped environments:** Download the BGE-small model files manually from HuggingFace and place them at `./model_assets/bge-small-en-v1.5/` before running.

---

## Repository Structure

```
kattalai/
├── src/                        # Rust — soulengine library
│   ├── main.rs                 # Standalone dev runner
│   ├── lib.rs                  # Library root + PyO3 PyRuntime bindings
│   ├── agent.rs                # Agent state machine, episode management
│   ├── appstore.rs             # App discovery, loading, embedding index
│   ├── config.rs               # TOML config loading
│   ├── embeddings.rs           # FastEmbed wrapper (BGE-small-en-v1.5)
│   ├── inference.rs            # LLM providers (Ollama, Gemini, HuggingFace, Sarvam)
│   ├── memory.rs               # Memory nodes, episodes, topic threads
│   ├── model.rs                # POS model (nlprule)
│   ├── source.rs               # Source/Role types
│   ├── terminal.rs             # Subprocess launcher for Python REPL apps
│   └── tool.rs                 # App and AppType definitions
│
├── pysrc/soulengine/
│   ├── __init__.py
│   └── kattalai.py             # Textual TUI — main Python entry point
│
├── apps/
│   ├── core_apps/              # Built-in apps (always available)
│   │   ├── calculator_app/
│   │   ├── clock_app/
│   │   ├── grep_app/
│   │   └── notes_app/
│   ├── other_apps/             # Optional/extended apps
│   │   ├── stock_tracker_app/
│   │   └── webpage_reader_app/
│   └── se_app_utils/           # Shared base classes for app authors
│       └── soulengine.py       # soul_engine_app + soul_engine_interface
│
├── configs/
│   ├── agents_config.toml
│   └── inference_config.toml
│
├── prompts/                    # Agent system prompt templates
├── model_assets/pos_model/     # Pre-compiled nlprule binaries
├── .github/workflows/
│   └── release.yml             # CI: maturin build + PyPI publish on tag push
├── Cargo.toml
└── LICENSE                     # AGPL-3.0
```

---

## License

Licensed under **[AGPL-3.0](LICENSE)**.

- ✅ Free for open-source and academic/research use.
- ⚠️ If you modify and **deploy as a service**, you must open-source your modifications under the same license.
- 💼 For **proprietary or SaaS** use without open-sourcing, a commercial license is available. See [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).

---

<div align="center">

**[PyPI](https://pypi.org/project/kattalai/)** · **[HTTP API](API-Readme.md)** · **[Python API](PYREADME.md)** · **[WhatsApp Community](https://chat.whatsapp.com/GpOBwFIloGE93LV7prsoxS?mode=gi_t)**

</div>
