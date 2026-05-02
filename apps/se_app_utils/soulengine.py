import json
import time
from time import sleep
import sys
import tkinter as tk
import argparse
import asyncio
import sys
import shlex
import inspect
import traceback
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
def smart_split(command: str):
    tokens = []
    current = []
    
    in_double = False
    in_single = False
    escape = False

    for ch in command:
        if escape:
            current.append(ch)
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            continue

        if ch == " " and not in_double and not in_single:
            if current:
                tokens.append("".join(current))
                current = []
            continue

        current.append(ch)

    if current:
        tokens.append("".join(current))

    return tokens

####################

import sys
import os
import json
import uuid
import time
from pathlib import Path


# ── Pipe-safe threshold ────────────────────────────────────────────────────────
# Windows named-pipe default buffer: 4 KB.
# Linux anonymous pipe: 64 KB.
# Stay well under the worst case so write() always completes atomically.
_PIPE_INLINE_LIMIT: int = 2048  # 2 KB


# ── Catppuccin Mocha palette (module-level, shared by all dialogs) ──────────
_CM_BG      = "#1e1e2e"
_CM_SURFACE = "#313244"
_CM_TEXT    = "#cdd6f4"
_CM_SUBTEXT = "#a6adc8"
_CM_BLUE    = "#89b4fa"
_CM_GREEN   = "#a6e3a1"
_CM_RED     = "#f38ba8"
_CM_YELLOW  = "#f9e2af"


class soul_engine_interface:
    """
    IPC bridge between a soul_engine app and the Rust runtime.
    ...
    """

    _spill_dir: Path = Path(sys.argv[0]).resolve().parent / "_se_spill"

    def __init__(self, args, app_name: str, app_icon: str = "🤖"):
        self.episode_id    = args.episode_id
        self.invocation_id = args.invocation_id
        self.app_name      = app_name
        self.app_icon      = app_icon          # e.g. "📚" for Codex, "🐚" for shell

    # ── internal ──────────────────────────────────────────────────────────────

    def _spill(self, msg: str) -> str:
        """..."""
        if len(msg.encode("utf-8")) <= _PIPE_INLINE_LIMIT:
            return msg

        self._spill_dir.mkdir(parents=True, exist_ok=True)
        unique_name = (
            f"se_spill"
            f"_ep{self.episode_id}"
            f"_inv{self.invocation_id}"
            f"_{int(time.time() * 1000)}"
            f"_{uuid.uuid4().hex}"
            f".json"
        )
        spill_path = self._spill_dir / unique_name
        spill_path.write_text(msg + "\n", encoding="utf-8")
        return json.dumps(
            {"__spilled__": True, "file": str(spill_path)},
            ensure_ascii=False,
        )

    def _send(self, frame_tag: str, msg: str) -> None:
        """..."""
        safe_msg = self._spill(msg)
        line = (
            f"[{frame_tag}>"
            f"episode_id:{self.episode_id}|"
            f"invocation_id:{self.invocation_id}]"
            f"{safe_msg}\n"
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    # ── public API ────────────────────────────────────────────────────────────

    def send_message(self, msg: str) -> None:
        """Send a result/response message back to the Rust runtime."""
        self._send("#APP_MESSAGE", msg)

    def send_and_invoke(self, msg: str) -> None:
        """Send a message that also triggers a follow-up invocation in Rust."""
        self._send("#APP_INVOKE", msg)

    def request_permission(
        self,
        action: str,
        context: dict,
        *,
        message: str | None = None,
        icon: str | None = None,
    ) -> bool:
        """
        Blocking Catppuccin Mocha tkinter permission dialog.

        Parameters
        ----------
        action  : short verb shown in the title bar, e.g. "EXECUTE", "READ"
        context : key/value pairs rendered in the detail box
        message : human-readable description of what is being requested.
                  Defaults to a generic fallback using app_name + action.
        icon    : emoji override; falls back to self.app_icon set at construction.

        Returns True → Allow, False → Deny / window closed.

        Usage (any app)
        ---------------
            allowed = se_interface.request_permission(
                action="execute",
                context={"command": cmd, "working dir": cwd},
                message="Allow running a shell command on your machine?",
            )
        """
        try:
            import tkinter as tk
        except ImportError:
            # Headless environment — fail closed.
            return False

        resolved_icon    = icon or self.app_icon
        resolved_message = (
            message
            or f"Allow {self.app_name} to perform '{action}' on this machine?"
        )

        result = {"allowed": False}

        root = tk.Tk()
        root.title(f"{self.app_name} — Permission Required")
        root.resizable(False, False)
        root.configure(bg=_CM_BG)

        root.update_idletasks()
        w, h = 500, 290
        x = (root.winfo_screenwidth()  - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Icon + title row ──────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=_CM_BG)
        hdr.pack(fill="x", padx=20, pady=(16, 0))

        tk.Label(
            hdr, text=resolved_icon,
            font=("Segoe UI Emoji", 22),
            fg=_CM_YELLOW, bg=_CM_BG,
        ).pack(side="left")

        tk.Label(
            hdr,
            text=f"{self.app_name} — Permission Required: {action.upper()}",
            font=("Segoe UI", 11, "bold"),
            fg=_CM_TEXT, bg=_CM_BG,
        ).pack(side="left", padx=(10, 0))

        # ── Message ───────────────────────────────────────────────────────────
        tk.Label(
            root, text=resolved_message,
            font=("Segoe UI", 9),
            fg=_CM_SUBTEXT, bg=_CM_BG,
            wraplength=460, justify="left",
        ).pack(fill="x", padx=20, pady=(8, 0))

        # ── Context detail box ────────────────────────────────────────────────
        box = tk.Frame(root, bg=_CM_SURFACE)
        box.pack(fill="x", padx=20, pady=10)

        for key, val in context.items():
            row = tk.Frame(box, bg=_CM_SURFACE)
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(
                row, text=f"{key}:", font=("Consolas", 9, "bold"),
                fg=_CM_BLUE, bg=_CM_SURFACE, width=14, anchor="w",
            ).pack(side="left")
            tk.Label(
                row, text=str(val), font=("Consolas", 9),
                fg=_CM_TEXT, bg=_CM_SURFACE, anchor="w",
            ).pack(side="left", fill="x")

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = tk.Frame(root, bg=_CM_BG)
        btns.pack(pady=(0, 16))

        def _allow():
            result["allowed"] = True
            root.destroy()

        def _deny():
            result["allowed"] = False
            root.destroy()

        tk.Button(
            btns, text="✕  Deny", command=_deny,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            bg=_CM_RED,   fg=_CM_BG, activebackground="#eba0ac",
            relief="flat", padx=18, pady=6,
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            btns, text="✓  Allow", command=_allow,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            bg=_CM_GREEN, fg=_CM_BG, activebackground="#94e2d5",
            relief="flat", padx=18, pady=6,
        ).pack(side="left")

        root.protocol("WM_DELETE_WINDOW", _deny)
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.mainloop()

        return result["allowed"]
###################
class soul_engine_app():
    def __init__(self,app_name:str, app_icon: str = "🤖"):
        self.app_name=app_name
        self.app_icon=app_icon
    def parse_line(self,line):
        try:
            tokens = shlex.split(line)
        except ValueError:
            print(f"Warning: Failed to parse line with shlex. Falling back to simple split. Line: {line}")
            # fallback if quotes are broken
            tokens = smart_split(line)

        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--episode_id")
        parser.add_argument("--invocation_id")

            

        args, remaining = parser.parse_known_args(tokens)
        # print(f"Remaining arguments: {list(enumerate(remaining))}")

        if not args.episode_id or not args.invocation_id:
            sys.stdout.write("[#COMMAND_ERROR>episode_id:{args.episode_id}|invocation_id:{args.invocation_id}]Missing episode_id or invocation_id\n")
            sys.stdout.flush()

        return args,remaining

    async def _process_line(self, line: str):
        args,remaining=self.parse_line(line)


        sys.stdout.write(f"[#COMMAND_RECEIVED>episode_id:{args.episode_id}|invocation_id:{args.invocation_id}]{remaining}\n")
        sys.stdout.flush()
        result=""
        try:
            result = await self.process_command(self.get_interface(args,self.app_name),remaining)
            if result is None:
                result="Application executed successfully.Check APP_MESSAGE for more details."

            # if result is not None:
            sys.stdout.write(f"[#APP_EXECUTION_SUCCESS>episode_id:{args.episode_id}|invocation_id:{args.invocation_id}]{result}\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(f"[#APP_EXECUTION_ERROR>episode_id:{args.episode_id}|invocation_id:{args.invocation_id}]ERROR:{str(e)}\n")

    async def _loop(self):
        loop = asyncio.get_running_loop()

        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            

            line = line.strip()
            if not line:
                continue

            if line and "[#TERMINATE_APP>" in line.strip():
                args,remaining=self.parse_line(line)

                sys.stdout.write("[#TERMINATING_APP>episode_id:{args.episode_id}|invocation_id:{args.invocation_id}]\n")
                sys.stdout.flush()
                break


            asyncio.create_task(self._process_line(line))

    def get_interface(self,args,app_name):
        return soul_engine_interface(args,app_name,self.app_icon)

    def run_one_shot(self):
        try:
            if not inspect.iscoroutinefunction(self.process_command):
                raise TypeError("self.process_command must be an async function")
            
            line = sys.argv
            if len(line)>0:
                line=" ".join(line[1:])
            else:
                line=""
            print(f"Launching App: {self.app_name}")
            asyncio.run(self._process_line(line))
        except Exception as e:
            sys.stdout.write(f"[#APP_ERROR>{str(e)}]")

    def run_repl(self):
        try:
            if not inspect.iscoroutinefunction(self.process_command):
                raise TypeError("self.process_command must be an async function")
            print(f"Launching App: {self.app_name}")
            asyncio.run(self._loop())
        except Exception as e:
            sys.stdout.write(f"[#APP_ERROR>{str(e)}]")


