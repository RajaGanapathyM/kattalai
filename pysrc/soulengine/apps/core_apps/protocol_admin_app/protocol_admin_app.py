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
from datetime import datetime
from pathlib import Path
import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


# ── Dialog messages ────────────────────────────────────────────────────────────
DIALOG_MESSAGES = {
    "run":    "Allow executing this shell command in the workspace?",
    "script": "Allow executing this shell script file?",
    "kill":   "Allow sending a signal to the specified process? This may terminate it.",
}


def _now() -> str:
    return datetime.now().isoformat()


class ShellApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="Shell App", app_icon="🐚")

    # ── Response builders ──────────────────────────────────────────────────────

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
        parsed = {}
        raw = " ".join(args)
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
            result = {"status": "error", "command": command, "reason": str(exc)}

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

        cwd         = kv.get("cwd", os.getcwd())
        include_env = kv.get("env", "false").lower() in ("true", "1", "yes")

        context = {"cmd": cmd, "cwd": cwd}
        if include_env:
            context["env"] = "inherited (current process environment)"

        if not si.request_permission(
            action="run",
            context=context,
            message=DIALOG_MESSAGES["run"],
        ):
            return self._denied("run", cmd=cmd, cwd=cwd)

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
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
        cwd        = kv.get("cwd", str(script_path.parent))

        if not si.request_permission(
            action="script",
            context={
                "script": str(script_path),
                "args":   extra_args or "(none)",
                "cwd":    cwd,
            },
            message=DIALOG_MESSAGES["script"],
        ):
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
                stdin=subprocess.DEVNULL,
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

        if not si.request_permission(
            action="kill",
            context={"pid": pid, "signal": sig_raw},
            message=DIALOG_MESSAGES["kill"],
        ):
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