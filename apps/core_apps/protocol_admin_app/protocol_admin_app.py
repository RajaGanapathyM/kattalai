# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import os
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path

import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

script_directory = Path(__file__).parent
SCHEDULES_FILE = Path("./configs/protocol_schedules.txt")

# ── Dialog messages ────────────────────────────────────────────────────────────
DIALOG_MESSAGES = {
    "edit":   "Allow editing the cron schedule for this protocol entry?",
    "delete": "Allow permanently deleting this protocol schedule entry? This cannot be undone.",
}

# ── Cron validation (6-part extended or 5-part standard) ──────────────────────
_CRON_RE = re.compile(
    r"^(\*|[0-9,\-\*/]+)\s+"   # second (optional 6th field handled below)
    r"(\*|[0-9,\-\*/]+)\s+"
    r"(\*|[0-9,\-\*/]+)\s+"
    r"(\*|[0-9,\-\*/]+)\s+"
    r"(\*|[0-9,\-\*/]+)"
    r"(\s+(\*|[0-9,\-\*/]+))?$"
)


def _valid_cron(expr: str) -> bool:
    return bool(_CRON_RE.match(expr.strip()))


def _now() -> str:
    return datetime.now().isoformat()


# ── Schedule file I/O ──────────────────────────────────────────────────────────

def _load_schedules() -> list[dict]:
    """Return list of {memory_id, cron_schedule, protocol_name} dicts."""
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SCHEDULES_FILE.exists():
        return []
    entries = []
    for raw_line in SCHEDULES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        entries.append({
            "memory_id":     parts[0].strip(),
            "cron_schedule": parts[1].strip(),
            "protocol_name": parts[2].strip(),
        })
    return entries


def _save_schedules(entries: list[dict]) -> None:
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{e['memory_id']}|{e['cron_schedule']}|{e['protocol_name']}"
        for e in entries
    ]
    SCHEDULES_FILE.write_text("\n".join(lines) + ("\n" if lines else ""),
                              encoding="utf-8")


def _find_entry(entries: list[dict], memory_id: str) -> dict | None:
    for e in entries:
        if e["memory_id"] == memory_id:
            return e
    return None


# ── App ────────────────────────────────────────────────────────────────────────

class ProtocolSchedulesApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="Protocol Schedules App")

    # ── Permission dialog ──────────────────────────────────────────────────────
    def _request_permission(self, command: str, context: dict) -> bool:
        """
        Opens a blocking tkinter dialog.
        Returns True if the user clicked Allow, False if Deny / closed the window.
        """
        result = {"allowed": False}

        root = tk.Tk()
        root.title("Protocol Schedules — Permission")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")

        root.update_idletasks()
        w, h = 480, 280
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Header ────────────────────────────────────────────────────────────
        icon_frame = tk.Frame(root, bg="#1e1e2e")
        icon_frame.pack(fill="x", padx=20, pady=(18, 0))

        tk.Label(icon_frame, text="⚙", font=("Segoe UI", 26),
                 fg="#cba6f7", bg="#1e1e2e").pack(side="left")

        tk.Label(icon_frame,
                 text=f"Permission Required — {command.upper()}",
                 font=("Segoe UI", 11, "bold"),
                 fg="#cdd6f4", bg="#1e1e2e").pack(side="left", padx=(10, 0), pady=4)

        # ── Message ───────────────────────────────────────────────────────────
        tk.Label(root, text=DIALOG_MESSAGES[command],
                 font=("Segoe UI", 10), fg="#a6adc8", bg="#1e1e2e",
                 wraplength=440, justify="left").pack(fill="x", padx=20, pady=(8, 0))

        # ── Context detail panel ──────────────────────────────────────────────
        detail_frame = tk.Frame(root, bg="#313244")
        detail_frame.pack(fill="x", padx=20, pady=10)

        for key, val in context.items():
            row = tk.Frame(detail_frame, bg="#313244")
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{key}:", font=("Consolas", 9, "bold"),
                     fg="#89dceb", bg="#313244", width=18, anchor="w").pack(side="left")
            tk.Label(row, text=str(val), font=("Consolas", 9),
                     fg="#cdd6f4", bg="#313244", anchor="w").pack(side="left", fill="x")

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(root, bg="#1e1e2e")
        btn_frame.pack(pady=(0, 16))

        def on_allow():
            result["allowed"] = True
            root.destroy()

        def on_deny():
            result["allowed"] = False
            root.destroy()

        tk.Button(btn_frame, text="✕  Deny", command=on_deny,
                  font=("Segoe UI", 10, "bold"), cursor="hand2",
                  bg="#f38ba8", fg="#1e1e2e", activebackground="#eba0ac",
                  relief="flat", padx=18, pady=6, bd=0).pack(side="left", padx=(0, 12))

        tk.Button(btn_frame, text="✓  Allow", command=on_allow,
                  font=("Segoe UI", 10, "bold"), cursor="hand2",
                  bg="#a6e3a1", fg="#1e1e2e", activebackground="#94e2d5",
                  relief="flat", padx=18, pady=6, bd=0).pack(side="left")

        root.protocol("WM_DELETE_WINDOW", on_deny)
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.mainloop()

        return result["allowed"]

    # ── Response factories ─────────────────────────────────────────────────────
    def _ok(self, command: str, **extra) -> dict:
        return {"status": "success", "command": command,
                "user_confirmed": True, "timestamp": _now(), **extra}

    def _denied(self, command: str, **extra) -> dict:
        return {"status": "denied", "command": command,
                "user_confirmed": False, "timestamp": _now(), **extra}

    # ── Argument parser ────────────────────────────────────────────────────────
    @staticmethod
    def _parse_args(args: list[str]) -> dict:
        parsed = {}
        for token in args:
            if "=" in token:
                k, _, v = token.partition("=")
                parsed[k.strip()] = v.strip().strip('"').strip("'")
            else:
                parsed.setdefault("_bare", []).append(token)
        return parsed

    # ── Main dispatcher ────────────────────────────────────────────────────────
    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": "No command provided. Valid commands: list, get, edit, delete",
            }))
            return

        command = args[0].lower()
        kv = self._parse_args(args[1:])

        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"Unknown command '{command}'. Valid commands: list, get, edit, delete",
            }))
            return

        try:
            result = await handler(kv)
        except Exception as exc:
            result = {"status": "error", "command": command, "reason": str(exc)}

        se_interface.send_message(json.dumps(result))

    # ══════════════════════════════════════════════════════════════════════════
    # READ commands
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_list(self, _kv: dict) -> dict:
        entries = _load_schedules()
        return {"status": "success", "command": "list", "entries": entries}

    async def _cmd_get(self, kv: dict) -> dict:
        memory_id = kv.get("memory_id")
        if not memory_id:
            return {"status": "error", "command": "get",
                    "reason": "Missing 'memory_id' argument."}

        entry = _find_entry(_load_schedules(), memory_id)
        if entry is None:
            return {"status": "error", "command": "get",
                    "error_code": "not_found",
                    "reason": f"No schedule found for memory_id: {memory_id}"}

        return {"status": "success", "command": "get", **entry}

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands (permission dialog required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_edit(self, kv: dict) -> dict:
        memory_id    = kv.get("memory_id")
        new_cron     = kv.get("cron_schedule")

        if not memory_id:
            return {"status": "error", "command": "edit",
                    "reason": "Missing 'memory_id' argument."}
        if not new_cron:
            return {"status": "error", "command": "edit",
                    "reason": "Missing 'cron_schedule' argument."}
        if not _valid_cron(new_cron):
            return {"status": "error", "command": "edit",
                    "error_code": "invalid_cron",
                    "reason": f"Invalid cron expression: '{new_cron}'"}

        entries = _load_schedules()
        entry   = _find_entry(entries, memory_id)
        if entry is None:
            return {"status": "error", "command": "edit",
                    "error_code": "not_found",
                    "reason": f"No schedule found for memory_id: {memory_id}"}

        old_cron = entry["cron_schedule"]

        allowed = self._request_permission("edit", {
            "memory_id":     memory_id,
            "protocol_name": entry["protocol_name"],
            "old_schedule":  old_cron,
            "new_schedule":  new_cron,
        })
        if not allowed:
            return self._denied("edit", memory_id=memory_id,
                                old_cron_schedule=old_cron,
                                new_cron_schedule=new_cron)

        entry["cron_schedule"] = new_cron
        _save_schedules(entries)

        return self._ok("edit", memory_id=memory_id,
                        old_cron_schedule=old_cron,
                        new_cron_schedule=new_cron)

    async def _cmd_delete(self, kv: dict) -> dict:
        memory_id = kv.get("memory_id")
        if not memory_id:
            return {"status": "error", "command": "delete",
                    "reason": "Missing 'memory_id' argument."}

        entries = _load_schedules()
        entry   = _find_entry(entries, memory_id)
        if entry is None:
            return {"status": "error", "command": "delete",
                    "error_code": "not_found",
                    "reason": f"No schedule found for memory_id: {memory_id}"}

        allowed = self._request_permission("delete", {
            "memory_id":     memory_id,
            "protocol_name": entry["protocol_name"],
            "cron_schedule": entry["cron_schedule"],
        })
        if not allowed:
            return self._denied("delete", memory_id=memory_id,
                                protocol_name=entry["protocol_name"])

        entries = [e for e in entries if e["memory_id"] != memory_id]
        _save_schedules(entries)

        return self._ok("delete", memory_id=memory_id,
                        protocol_name=entry["protocol_name"])


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ProtocolSchedulesApp()
    app.run_repl()