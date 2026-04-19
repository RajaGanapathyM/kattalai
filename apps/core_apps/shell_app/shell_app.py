# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


# ── Dialog messages mirrored from TOML ────────────────────────────────────────
DIALOG_MESSAGES = {
    "run":    "Allow executing this shell command in the workspace?",
    "script": "Allow executing this shell script file?",
    "kill":   "Allow sending a signal to the specified process? This may terminate it.",
}


def _now() -> str:
    return datetime.now().isoformat()


class ShellApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="Shell App")

    # ── Permission dialog ──────────────────────────────────────────────────────
    def _request_permission(self, _si, command: str, context: dict) -> bool:
        """
        Opens a blocking tkinter dialog.
        Returns True if the user clicked Allow, False if Deny / closed the window.
        """
        result = {"allowed": False}

        root = tk.Tk()
        root.title("Shell Operation Permission")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")

        # Centre on screen
        root.update_idletasks()
        w, h = 520, 280
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Icon row ──────────────────────────────────────────────────────────
        icon_frame = tk.Frame(root, bg="#1e1e2e")
        icon_frame.pack(fill="x", padx=20, pady=(18, 0))

        icon_lbl = tk.Label(icon_frame, text="⚠", font=("Segoe UI", 26),
                            fg="#fab387", bg="#1e1e2e")
        icon_lbl.pack(side="left")

        title_lbl = tk.Label(icon_frame,
                             text=f"Permission Required — {command.upper()}",
                             font=("Segoe UI", 11, "bold"),
                             fg="#cdd6f4", bg="#1e1e2e")
        title_lbl.pack(side="left", padx=(10, 0), pady=4)

        # ── Message ───────────────────────────────────────────────────────────
        msg_lbl = tk.Label(root, text=DIALOG_MESSAGES[command],
                           font=("Segoe UI", 10), fg="#a6adc8", bg="#1e1e2e",
                           wraplength=480, justify="left")
        msg_lbl.pack(fill="x", padx=20, pady=(8, 0))

        # ── Context details ───────────────────────────────────────────────────
        detail_frame = tk.Frame(root, bg="#313244", highlightthickness=0)
        detail_frame.pack(fill="x", padx=20, pady=10)

        for key, val in context.items():
            row = tk.Frame(detail_frame, bg="#313244")
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{key}:", font=("Consolas", 9, "bold"),
                     fg="#89dceb", bg="#313244", width=12, anchor="w").pack(side="left")
            tk.Label(row, text=str(val), font=("Consolas", 9),
                     fg="#cdd6f4", bg="#313244", anchor="w",
                     wraplength=370, justify="left").pack(side="left", fill="x")

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(root, bg="#1e1e2e")
        btn_frame.pack(pady=(0, 16))

        def on_allow():
            result["allowed"] = True
            root.destroy()

        def on_deny():
            result["allowed"] = False
            root.destroy()

        deny_btn = tk.Button(btn_frame, text="✕  Deny", command=on_deny,
                             font=("Segoe UI", 10, "bold"), cursor="hand2",
                             bg="#f38ba8", fg="#1e1e2e", activebackground="#eba0ac",
                             relief="flat", padx=18, pady=6, bd=0)
        deny_btn.pack(side="left", padx=(0, 12))

        allow_btn = tk.Button(btn_frame, text="✓  Allow", command=on_allow,
                              font=("Segoe UI", 10, "bold"), cursor="hand2",
                              bg="#a6e3a1", fg="#1e1e2e", activebackground="#94e2d5",
                              relief="flat", padx=18, pady=6, bd=0)
        allow_btn.pack(side="left")

        root.protocol("WM_DELETE_WINDOW", on_deny)  # closing = deny
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.mainloop()

        return result["allowed"]

    def _denied(self, command: str, **extra) -> dict:
        return {
            "status": "denied",
            "command": command,
            "permission_dialog_shown": True,
            "user_confirmed": False,
            "timestamp": _now(),
            **extra,
        }

    def _ok(self, command: str, **extra) -> dict:
        return {
            "status": "success",
            "command": command,
            "permission_dialog_shown": True,
            "user_confirmed": True,
            "timestamp": _now(),
            **extra,
        }

    # ── Argument parser ────────────────────────────────────────────────────────
    @staticmethod
    def _parse_args(args: list[str]) -> dict:
        """
        Parses key=value tokens. Values may be quoted or unquoted.
        Handles multi-word quoted values reassembled from tokenised input.
        """
        parsed = {}
        raw = " ".join(args)
        # Use shlex to respect quoted strings around values
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = args

        i = 0
        while i < len(tokens):
            token = tokens[i]
            if "=" in token:
                k, _, v = token.partition("=")
                parsed[k.strip()] = v.strip().strip('"').strip("'")
            else:
                parsed.setdefault("_bare", []).append(token)
            i += 1
        return parsed

    # ── Main dispatcher ────────────────────────────────────────────────────────
    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": "No command provided.",
            }))
            return

        command = args[0].lower()
        kv = self._parse_args(args[1:])

        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": (
                    f"Unknown command '{command}'. "
                    "Valid commands: run, script, which, env, kill"
                ),
            }))
            return

        try:
            result = await handler(se_interface, kv)
        except Exception as exc:
            result = {
                "status": "error",
                "command": command,
                "reason": str(exc),
            }

        se_interface.send_message(json.dumps(result))

    # ══════════════════════════════════════════════════════════════════════════
    # READ commands (no dialog)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_which(self, _si, kv: dict) -> dict:
        cmd = kv.get("cmd")
        if not cmd:
            return {"status": "error", "command": "which",
                    "reason": "Missing 'cmd' argument."}

        resolved = shutil.which(cmd)
        return {
            "status": "success",
            "command": "which",
            "cmd": cmd,
            "resolved_path": resolved or "",
            "found": resolved is not None,
            "timestamp": _now(),
        }

    async def _cmd_env(self, _si, kv: dict) -> dict:
        return {
            "status": "success",
            "command": "env",
            "variables": dict(os.environ),
            "timestamp": _now(),
        }

    # ══════════════════════════════════════════════════════════════════════════
    # EXECUTE commands (permission dialog required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_run(self, si, kv: dict) -> dict:
        cmd = kv.get("cmd")
        if not cmd:
            return {"status": "error", "command": "run",
                    "reason": "Missing 'cmd' argument."}

        cwd = kv.get("cwd", os.getcwd())
        include_env = kv.get("env", "false").lower() in ("true", "1", "yes")

        context = {"cmd": cmd, "cwd": cwd}
        if include_env:
            context["env"] = "inherited (current process environment)"

        allowed = self._request_permission(si, "run", context)
        if not allowed:
            return self._denied("run", cmd=cmd, cwd=cwd)

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ if include_env else None,
                text=True,
            )
            stdout, stderr = proc.communicate()
            duration_ms = int((time.monotonic() - start) * 1000)

            return self._ok(
                "run",
                cmd=cmd,
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                pid=proc.pid,
            )
        except FileNotFoundError:
            return {
                "status": "error",
                "command": "run",
                "error_code": "command_not_found",
                "reason": f"Command not found: {cmd}",
                "timestamp": _now(),
            }
        except PermissionError as e:
            return {
                "status": "error",
                "command": "run",
                "error_code": "permission_denied",
                "reason": str(e),
                "timestamp": _now(),
            }

    async def _cmd_script(self, si, kv: dict) -> dict:
        path_raw = kv.get("path")
        if not path_raw:
            return {"status": "error", "command": "script",
                    "reason": "Missing 'path' argument."}

        script_path = Path(os.path.expanduser(path_raw)).resolve()
        if not script_path.exists():
            return {"status": "error", "command": "script",
                    "error_code": "path_not_found",
                    "reason": f"Script does not exist: {script_path}"}
        if not script_path.is_file():
            return {"status": "error", "command": "script",
                    "error_code": "not_a_file",
                    "reason": f"Path is not a file: {script_path}"}

        extra_args = kv.get("args", "")
        cwd = kv.get("cwd", str(script_path.parent))

        context = {
            "script": str(script_path),
            "args": extra_args or "(none)",
            "cwd": cwd,
        }

        allowed = self._request_permission(si, "script", context)
        if not allowed:
            return self._denied("script", path=str(script_path), cwd=cwd)

        full_cmd = f"bash {shlex.quote(str(script_path))}"
        if extra_args:
            full_cmd += f" {extra_args}"

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                full_cmd,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate()
            duration_ms = int((time.monotonic() - start) * 1000)

            return self._ok(
                "script",
                path=str(script_path),
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                pid=proc.pid,
            )
        except PermissionError as e:
            return {
                "status": "error",
                "command": "script",
                "error_code": "permission_denied",
                "reason": str(e),
                "timestamp": _now(),
            }

    async def _cmd_kill(self, si, kv: dict) -> dict:
        pid_raw = kv.get("pid")
        if not pid_raw:
            return {"status": "error", "command": "kill",
                    "reason": "Missing 'pid' argument."}

        try:
            pid = int(pid_raw)
        except ValueError:
            return {"status": "error", "command": "kill",
                    "reason": f"Invalid pid value: '{pid_raw}'. Must be an integer."}

        sig_raw = kv.get("signal", "SIGTERM").upper()
        sig_map = {
            "SIGTERM": signal.SIGTERM,
            "SIGKILL": signal.SIGKILL,
            "SIGINT":  signal.SIGINT,
            "SIGHUP":  signal.SIGHUP,
        }
        sig = sig_map.get(sig_raw)
        if sig is None:
            return {"status": "error", "command": "kill",
                    "reason": f"Unknown signal '{sig_raw}'. "
                               "Supported: SIGTERM, SIGKILL, SIGINT, SIGHUP"}

        context = {"pid": pid, "signal": sig_raw}
        allowed = self._request_permission(si, "kill", context)
        if not allowed:
            return self._denied("kill", pid=pid, signal=sig_raw)

        try:
            os.kill(pid, sig)
            return self._ok("kill", pid=pid, signal=sig_raw, proc_status="sent")
        except ProcessLookupError:
            return {
                "status": "error",
                "command": "kill",
                "error_code": "process_not_found",
                "reason": f"No process with pid {pid}.",
                "pid": pid,
                "timestamp": _now(),
            }
        except PermissionError:
            return {
                "status": "error",
                "command": "kill",
                "error_code": "permission_denied",
                "reason": f"Not permitted to signal process {pid}.",
                "pid": pid,
                "timestamp": _now(),
            }


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ShellApp()
    app.run_repl()