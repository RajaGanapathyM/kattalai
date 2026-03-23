# kattalai — Setup & Usage Guide

> **An AI agent runtime that builds and executes Python apps to act as a coworker.**
> Core engine in Rust (`soulengine`), exposed to Python via PyO3/maturin, with a Textual TUI frontend.

### To be precise: Like Anthropic's Claude for teamwork—build your Python apps, give them to Kattalai, and it figures out how to use them.

### Join our discord server for active discussions: https://discord.com/invite/T9bsnJSg7

---
![kattalai banner](assets/banner_img_kattalai.png)

---

## ⚡ Quick Install (PyPI)

```bash
pip3 install kattalai
```

> **⚠️ PATH Warning:** After install, pip may show a warning like:
> ```
> WARNING: The script kattalai is installed in 'C:\Users\<you>\AppData\Local\...\Scripts'
> which is not on PATH.
> ```
> Copy that Scripts path from the warning and add it to your PATH, then open a new terminal. The `kattalai` command will work after that.
>
> **Windows quick fix:**
> ```bash
> setx PATH "%PATH%;<paste the Scripts path from the warning here>"
> ```

Once installed, run the first-time setup to download apps, configs, prompts, and model assets from GitHub:

```bash
kattalai-setup
```

Then launch the agent:

```bash
kattalai
```

To view or edit your configs, apps, and prompts — open the install folder directly in your file explorer:

```bash
kattalai-folder
```

> **Note:** `torch` and `numpy` are installed automatically as dependencies (~2 GB). On Windows, PyTorch is required to fix DLL loading for `soulengine`.

---

## Table of Contents

1. [What is kattalai?](#1-what-is-kattalai)
2. [Repository Structure](#2-repository-structure)
3. [Prerequisites](#3-prerequisites)
4. [Installation](#4-installation)
   - [Option A — Install from PyPI (recommended)](#option-a--install-from-pypi-recommended)
   - [Option B — Build from source (for development)](#option-b--build-from-source)
5. [Configuration](#5-configuration)
   - [inference_config.toml](#inference_configtoml)
   - [agents_config.toml](#agents_configtoml)
6. [Running the Runtime (Rust binary)](#6-running-the-runtime-rust-binary)
7. [Running the TUI (Python frontend)](#7-running-the-tui-python-frontend)
8. [Apps System](#8-apps-system)
   - [App TOML Schema](#app-toml-schema)
   - [Core Apps](#core-apps)
   - [Other Apps](#other-apps)
   - [Writing a New App](#writing-a-new-app)
9. [Prompts](#9-prompts)
10. [Model Assets](#10-model-assets)
11. [License](#11-license)

---

## 1. What is kattalai?

**kattalai** (Tamil: *கட்டளை*, meaning "command") is an agent runtime that sits between a user and the operating system. Rather than exposing raw OS commands, it orchestrates focused Python utility apps — each defined by a TOML config — and routes user intent to the right app using LLM reasoning, NLP classification, and embedding-based semantic search.

The system is split into two layers:

- **`soulengine`** — a Rust library that handles agent lifecycle, memory, inference, app discovery, and tool routing. It is also compiled as a Python extension (via PyO3) so it can be driven from Python.
- **`kattalai.py`** — a Python Textual TUI that uses the `PyRuntime` class from `soulengine` to present a chat/agent interface to the user.

---

## 2. Repository Structure

```
kattalai/
├── src/                        # Rust source — the soulengine library
│   ├── main.rs                 # Standalone Rust binary (demo/dev runner)
│   ├── lib.rs                  # Library root + PyO3 PyRuntime bindings
│   ├── agent.rs                # Agent state machine, episode management
│   ├── appstore.rs             # App discovery, loading, and embedding index
│   ├── config.rs               # TOML config loading (agents + inference)
│   ├── embeddings.rs           # FastEmbed wrapper (BGE-small-en-v1.5)
│   ├── inference.rs            # LLM provider implementations (Ollama, Gemini, HuggingFace, Sarvam)
│   ├── memory.rs               # Memory nodes, episodes, topic threads
│   ├── model.rs                # POS model (nlprule)
│   ├── source.rs               # Source/Role types (User, Agent, App)
│   ├── terminal.rs             # Subprocess launcher for Python REPL apps
│   └── tool.rs                 # App and AppType definitions
│
├── pysrc/
│   └── soulengine/
│       ├── __init__.py
│       └── kattalai.py         # Textual TUI — main Python entry point
│
├── apps/                       # Python utility apps
│   ├── core_apps/              # Built-in system apps (always available)
│   │   ├── calculator_app/
│   │   ├── clock_app/
│   │   ├── grep_app/
│   │   └── notes_app/
│   ├── other_apps/             # Extended/optional apps
│   │   ├── stock_tracker_app/
│   │   └── webpage_reader_app/
│   └── se_app_utils/           # Shared Python base classes for app authors
│       └── soulengine.py       # soul_engine_app + soul_engine_interface
│
├── configs/
│   ├── agents_config.toml      # Agent definitions (name, goal, models, default apps)
│   └── inference_config.toml   # LLM provider credentials and settings
│
├── prompts/                    # Agent system prompt templates (Markdown)
│   ├── AGENT_OPERATING_RULES.md
│   ├── AGENT_RAC_PROMPT.md
│   ├── AGENT_REASONING_PROMPT.md
│   ├── AGENT_RESPONSE_REPAIR_PROMPT.md
│   ├── AGENT_TOT_PROMPT.md
│   └── CONTEXT_TAGGING_PROMPT.md
│
├── model_assets/
│   └── pos_model/              # Pre-compiled nlprule binaries (en, de, es)
│
├── .github/workflows/
│   └── release.yml             # CI: maturin build + PyPI publish on tag push
│
├── Cargo.toml                  # Rust workspace manifest
├── Cargo.lock
├── LICENSE                     # AGPL-3.0
└── COMMERCIAL_LICENSE.md
```

---

## 3. Prerequisites

| Dependency | Version | Purpose |
|---|---|---|
| Python | 3.9 – 3.13 | TUI and app scripts |
| Ollama *(optional)* | latest | Local LLM inference |
| Rust + Cargo *(source only)* | ≥ 1.85 (edition 2024) | Build the `soulengine` crate |
| maturin *(source only)* | ≥ 1.x | Build the PyO3 Python extension |

Install Ollama (for local inference without API keys):

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Then pull the default reasoning model
ollama pull qwen3:4b

# And the lightweight NLP model
ollama pull qwen3:0.6b
```

---

## 4. Installation

### Option A — Install from PyPI (recommended)

```bash
pip3 install kattalai
```

> **⚠️ PATH Warning:** After install, pip may print a warning such as:
> ```
> WARNING: The script kattalai is installed in 'C:\Users\<you>\AppData\Local\...\Scripts'
> which is not on PATH.
> ```
> Copy the Scripts path shown in the warning and add it to your system PATH. Open a new terminal after doing so.
>
> **Windows quick fix:**
> ```bash
> setx PATH "%PATH%;<paste the Scripts path from the warning here>"
> ```
> Then open a new terminal and the `kattalai` command will work.

Run the first-time setup to download apps, configs, prompts, and model assets from GitHub:

```bash
kattalai-setup
```

This downloads everything kattalai needs into the install directory. You only need to do this once.

To view or edit your configs, apps, and prompts, open the install folder in your file explorer:

```bash
kattalai-folder
```

This opens the kattalai install directory — `configs/`, `apps/`, `prompts/`, and `model_assets/` will all be there after running `kattalai-setup`.

Install the remaining Python dependencies:

```bash
pip3 install textual yfinance playwright
pip3 install torch>=2.4.0
pip3 install "numpy<2"

# Optional: for the webpage reader app
playwright install chromium
```

Then launch:

```bash
kattalai
```

---

### Option B — Build from source

For development or if you want to modify the Rust core:

```bash
# 1. Clone the repo
git clone https://github.com/RajaGanapathyM/kattalai.git
cd kattalai

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate.bat     # Windows

# 3. Build and install the soulengine Python extension
pip3 install maturin
maturin develop --release

# 4. Install Python dependencies for the TUI and apps
pip3 install textual yfinance playwright
pip3 install torch==2.4.0
pip3 install "numpy<2"

# 5. (Optional) Install Playwright browser for the webpage reader app
playwright install chromium
```

> **Note for Windows users:** If you hit DLL loading errors at startup, ensure PyTorch is installed (`pip3 install torch`) so that `kattalai.py` can add its lib directory to the DLL search path automatically.

When building from source, `apps/`, `configs/`, `prompts/`, and `model_assets/` are already present in the cloned repo — no need to run `kattalai-setup`.

To open the project folder in your file explorer:

```bash
kattalai-folder
```

---

## 5. Configuration

All configuration lives in `configs/`. If you installed from PyPI, run `kattalai-folder` to open the install directory and navigate to `configs/` from there. If you cloned from source, the configs are at `./configs/` in the repo root.

### `inference_config.toml`

Defines credentials and parameters for each supported LLM provider. Only fill in the providers you intend to use.

```toml
[[ollama_config]]
chat_api_url    = "http://localhost:11434/api/chat"
generate_api_url = "http://localhost:11434/api/generate"
temperature     = 0.1

[[gemini_config]]
api_key     = "YOUR_GEMINI_API_KEY"
temperature = 0.1

[[huggingface_config]]
api_key        = "YOUR_HF_API_KEY"
max_new_tokens = 8000
temperature    = 0.1

[[sarvam_config]]
api_key        = "YOUR_SARVAM_API_KEY"
max_new_tokens = 8000
temperature    = 0.1
reasoning_effort = "high"
```

Supported `inference_provider` values (used in `agents_config.toml`): `ollama`, `gemini`, `huggingface`, `sarvam`.

### `agents_config.toml`

Defines one or more agents. Each `[[agent_config]]` block creates a named agent that the runtime can deploy.

```toml
[[agent_config]]
agent_name   = "DIA"
agent_goal   = "To assist user with their queries"
backstory    = "You are an AI assistant"

# Primary reasoning model — used for thinking and planning
reasoning_model = { inference_provider = "ollama", model_id = "qwen3:4b" }

# Lightweight NLP model — used for fast classification and routing
nlp_model = { inference_provider = "ollama", model_id = "qwen3:0.6b" }

# Apps the agent has access to on startup
default_apps = ["clock_app"]
```

You can swap providers per-agent. For example, to use Gemini for reasoning:

```toml
reasoning_model = { inference_provider = "gemini", model_id = "gemini-2.5-flash" }
```

---

## 6. Running the Runtime (Rust binary)

The Rust binary in `src/main.rs` is a development harness — it directly exercises the `Runtime` API without the TUI. Run it from the repo root so that relative paths (`./apps/`, `./configs/`, `./model_assets/`) resolve correctly.

```bash
cargo run --release
```

What it does on startup:

1. Initialises the FastEmbed embedder from `./model_assets/bge-small-en-v1.5` (auto-downloaded on first run).
2. Scans `./apps/` recursively for `*.toml` files and loads every app into the `AppStore`.
3. Loads `./configs/inference_config.toml` and `./configs/agents_config.toml`.
4. Creates a demo user ("Alice"), a topic thread, and deploys the "DIA" agent.
5. Sends test messages and prints memory state.

This is useful to verify your environment compiles and configs are valid before running the TUI.

> **Important:** Always run from the repo root (`cd kattalai && cargo run --release`), not from inside `src/`.

---

## 7. Running the TUI (Python frontend)

`pysrc/soulengine/kattalai.py` is a self-contained Textual application. It imports `PyRuntime` from the compiled `soulengine` extension and falls back to a demo mode if the native module is unavailable.

```bash
# With the virtual environment active:
kattalai
# or
python ./pysrc/soulengine/kattalai.py
```

The TUI has three tabs:

- **Chat** — send messages to the deployed agent; responses appear as structured blocks (thought / exec / output).
- **Agent Thoughts** — live view of the agent's internal reasoning episode for the current topic.
- **Logs** — raw terminal output from app subprocesses.

On startup it calls `PyRuntime.create()`, which runs the same initialisation sequence as the Rust binary (embedder → app store → inference store → agent store).

---

## 8. Apps System

Apps are the tools that agents use to act in the world. Each app is a self-contained Python script paired with a TOML config file that describes its capabilities.

### App TOML Schema

Every app config follows this schema:

```toml
app_name         = "Human-readable name"
app_path         = "./apps/core_apps/my_app/my_app.py"
app_start_command = "python"
app_start_args   = "./apps/core_apps/my_app/my_app.py"
app_handle_name  = "my_app"          # The handle used in agent commands: &my_app ...
app_launch_mode  = "REPL"            # "REPL" (persistent) or "ONE_SHOT" (per-invocation)

app_usage_guideline = """
Describe when and how to use this app. This text is embedded and
used by the agent to select the right app for a given task.
"""

[[app_command_signatures]]
command  = "command_name"
consumes = ["input_type_1", "input_type_2"]
produces = ["output_type"]
action   = "read"                    # 1–2 word verb: read, write, compute, search, etc.
```

The `app_handle_name` becomes the invocation handle — agents call apps using the pattern `&<handle_name> <args>`.

### Core Apps

These apps are loaded by default and cover fundamental system utilities.

| Handle | Mode | Description |
|---|---|---|
| `clock_app` | REPL | Set alarms, get current time. `&clock_app 5m Coffee break` |
| `notes_app` | ONE_SHOT | Full-featured note-taking with tags, search, backup. `&notes_app read --tag bug` |
| `grep_app` | REPL | Regex/literal file search with context, recursive walk, stdin search. `&grep_app search "TODO" ./src` |
| `calculator_app` | REPL | Arithmetic and expression evaluation with persistent variable store. |

### Other Apps

These are optional and may require additional Python dependencies. (Not yet completely tested)

| Handle | Mode | Description |
|---|---|---|
| `stock_tracker` | REPL | Live quotes, fundamentals, history, watchlist, and price alerts via `yfinance`. Indian NSE/BSE symbols supported (`.NS`, `.BO` suffix). `&stock_tracker quote HDFCBANK.NS` |
| `webpage_reader` | REPL | Fetch and extract web page content via Playwright (requires `playwright install chromium`). |

### Writing a New App

1. Create a folder under `apps/core_apps/` or `apps/other_apps/`.
2. Write a Python script that imports and uses `soul_engine_app` from `apps/se_app_utils/soulengine.py`.
3. Create a matching `.toml` config file following the schema above.
4. The `AppStore` automatically discovers any `*.toml` file under `./apps/` at startup — no registration step needed.

The `soul_engine_app` base class handles the REPL loop, argument parsing, and the structured message protocol (`[#APP_MESSAGE>...]`, `[#APP_INVOKE>...]`) that the Rust terminal layer reads.

---

## 9. Prompts

The `prompts/` directory contains Markdown files that define the agent's reasoning behaviour. These are loaded by the agent at runtime to construct system prompts.

| File | Purpose |
|---|---|
| `AGENT_OPERATING_RULES.md` | Hard constraints and invariants the agent must always follow |
| `AGENT_REASONING_PROMPT.md` | Base reasoning loop instructions |
| `AGENT_RAC_PROMPT.md` | ReAct + Critique pattern — think, act, critique cycle |
| `AGENT_TOT_PROMPT.md` | Tree of Thoughts reasoning with multi-branch exploration |
| `AGENT_RESPONSE_REPAIR_PROMPT.md` | Repair prompt for malformed structured responses |
| `CONTEXT_TAGGING_PROMPT.md` | Context labelling for multi-turn handoffs |

To customise agent behaviour, edit these files directly. Run `kattalai-folder` to open the install directory and find them under `prompts/`. The agent picks up changes on next initialisation — no recompile required.

---

## 10. Model Assets

The `model_assets/` directory holds pre-compiled binary assets that are required at startup.

**`model_assets/pos_model/`** — nlprule POS (Part-of-Speech) tagger binaries for English, German, and Spanish. These are used by the Rust `PosModel` for lightweight NLP classification without an LLM call. The binaries are already bundled in the repo; no download needed.

**`model_assets/bge-small-en-v1.5/`** *(auto-downloaded)* — The FastEmbed sentence embedding model used to build the app capability index. On first run, `fastembed` will download this model automatically from HuggingFace into `./model_assets/bge-small-en-v1.5/`. After the first run the directory will be populated and subsequent starts are instant.

If you are in an air-gapped environment, manually download the BGE-small model files and place them at `./model_assets/bge-small-en-v1.5/` before running.

---

## 11. License

This project is licensed under **AGPL-3.0**.

- Free for open-source and academic/research use.
- If you modify and **deploy as a service**, you must open-source your modifications under the same license.
- For use in a **proprietary product or SaaS** without open-sourcing, a commercial license is required. See [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md) for details.