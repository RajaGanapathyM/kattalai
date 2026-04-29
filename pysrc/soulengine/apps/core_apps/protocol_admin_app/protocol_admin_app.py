# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import tempfile
import tkinter as tk

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback: pip install tomli

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Constants ──────────────────────────────────────────────────────────────────
PROTOCOLS_DIR = Path("./protocols")
SCHEDULE_FILE = Path("./configs/protocol_schedules.txt")

DIALOG_MESSAGES = {
    "create":          "Allow creating a new protocol TOML file?",
    "update_meta":     "Allow updating protocol metadata fields?",
    "add_steps":       "Allow adding new steps to this protocol?",
    "edit_steps":      "Allow editing existing steps in this protocol?",
    "delete_steps":    "Allow deleting steps from this protocol?",
    "delete_protocol": "Allow permanently deleting this protocol file? This cannot be undone.",
    "edit_schedule":   "Allow editing the cron schedule for this protocol entry?",
    "delete_schedule": "Allow permanently deleting this schedule entry? This cannot be undone.",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _protocol_path(handle: str) -> Path:
    return PROTOCOLS_DIR / f"{handle}.toml"


def _load_protocol(handle: str) -> dict:
    path = _protocol_path(handle)
    if not path.exists():
        raise FileNotFoundError(f"Protocol file not found: {path}")
    with open(path, "rb") as f:
        return tomllib.load(f)


def _write_protocol(handle: str, data: dict) -> Path:
    """Serialize a protocol dict back to TOML and write it."""
    path = _protocol_path(handle)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []

    # Top-level metadata keys (in preferred order)
    meta_keys = [
        "protocol_name", "protocol_handle_name", "protocol_description",
        "trigger_prompt", "protocol_result", "apps_used",
    ]
    for key in meta_keys:
        if key in data:
            val = data[key]
            lines.append(f'{key} = {_toml_value(val)}')

    # Extra top-level keys not in the standard list
    standard_keys = set(meta_keys) | {"step"}
    for key, val in data.items():
        if key not in standard_keys:
            lines.append(f'{key} = {_toml_value(val)}')

    # Steps
    for step in data.get("step", []):
        lines.append("")
        lines.append("[[step]]")
        step_keys = ["id", "label", "app_command", "prompt", "completion_check_condition"]
        for sk in step_keys:
            if sk in step:
                lines.append(f'{sk} = {_toml_value(step[sk])}')
        # Any extra keys
        for sk, sv in step.items():
            if sk not in step_keys:
                lines.append(f'{sk} = {_toml_value(sv)}')

    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _toml_value(val) -> str:
    """Convert a Python value to its TOML literal representation."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(val)
    if isinstance(val, list):
        items = ", ".join(_toml_value(v) for v in val)
        return f"[{items}]"
    # String – use multi-line literal if contains newlines, else basic string
    s = str(val)
    if "\n" in s:
        return f'"""\n{s}\n"""'
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _renumber_steps(steps: list) -> list:
    """Reassign sequential IDs starting from 1."""
    for i, step in enumerate(steps, 1):
        step["id"] = i
    return steps


def _parse_json_arg(raw: str, arg_name: str):
    """Parse a JSON argument, raising ValueError on failure."""
    try:
        # print(f"Parsing JSON for argument '{arg_name}': {raw}")
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for '{arg_name}': {exc}") from exc


def _load_schedule_entries() -> list[dict]:
    if not SCHEDULE_FILE.exists():
        return []
    entries = []
    for line in SCHEDULE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append({
                "schedule_id": parts[0],
                "memory_id": parts[1],
                "cron_schedule": parts[2],
                "protocol_name": parts[3],
            })
    return entries


def _save_schedule_entries(entries: list[dict]) -> None:
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for e in entries:
        try:
            line = f"{e['schedule_id']}|{e['cron_schedule']}|{e['protocol_name']}|e['context']"
            lines.append(line)
        except KeyError as ex:
            raise ValueError(f"Missing key in entry: {ex}")

    content = "\n".join(lines) + ("\n" if lines else "")

    # 🔥 atomic write
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=SCHEDULE_FILE.parent, encoding="utf-8"
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    tmp_path.replace(SCHEDULE_FILE)

def _validate_cron(cron: str) -> bool:
    """Very basic cron validation: 5 or 6 space-separated fields."""
    parts = cron.strip().split()
    return len(parts) in (5, 6)


# ── App ────────────────────────────────────────────────────────────────────────

class ProtocolAdminApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="Protocol Admin App")

    # ── Permission dialog ──────────────────────────────────────────────────────
    def _request_permission(self, command: str, context: dict) -> bool:
        result = {"allowed": False}

        root = tk.Tk()
        root.title("Protocol Operation Permission")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")

        root.update_idletasks()
        w, h = 500, 300
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # Icon + title row
        icon_frame = tk.Frame(root, bg="#1e1e2e")
        icon_frame.pack(fill="x", padx=20, pady=(18, 0))

        tk.Label(icon_frame, text="⚠", font=("Segoe UI", 26),
                 fg="#f38ba8", bg="#1e1e2e").pack(side="left")
        tk.Label(icon_frame,
                 text=f"Permission Required — {command.upper()}",
                 font=("Segoe UI", 11, "bold"),
                 fg="#cdd6f4", bg="#1e1e2e").pack(side="left", padx=(10, 0), pady=4)

        # Message
        tk.Label(root, text=DIALOG_MESSAGES.get(command, "Allow this operation?"),
                 font=("Segoe UI", 10), fg="#a6adc8", bg="#1e1e2e",
                 wraplength=460, justify="left").pack(fill="x", padx=20, pady=(8, 0))

        # Context details
        detail_frame = tk.Frame(root, bg="#313244")
        detail_frame.pack(fill="x", padx=20, pady=10)

        for key, val in context.items():
            row = tk.Frame(detail_frame, bg="#313244")
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{key}:", font=("Consolas", 9, "bold"),
                     fg="#89b4fa", bg="#313244", width=14, anchor="w").pack(side="left")
            display_val = str(val)
            if len(display_val) > 55:
                display_val = display_val[:52] + "..."
            tk.Label(row, text=display_val, font=("Consolas", 9),
                     fg="#cdd6f4", bg="#313244", anchor="w").pack(side="left", fill="x")

        # Buttons
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
        # rgs_Str="\n".join([f"{i}: {arg}" for i, arg in enumerate(args)])
        # print(f"Raw arguments: {rgs_Str}")
        parsed = {}
        i = 0

        while i < len(args):
            token = args[i]

            if token.startswith("--"):
                key = token[2:]

                # Next token is the value
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    parsed[key] = args[i + 1]
                    i += 2
                else:
                    parsed[key] = True  # flag
                    i += 1
            else:
                i += 1
        # print(f"Parsed arguments: {parsed}")
        return parsed
    # def _parse_args(args: list[str]) -> dict:
    #     """
    #     Parses key=value tokens. Supports quoted values spanning multiple tokens.
    #     """
    #     raw = " ".join(args)
    #     parsed = {}
    #     # Match key=value where value may be a quoted string (single or double) or unquoted word
    #     pattern = re.compile(
    #         r'--(\w+)\s+'              # --key
    #         r'(?:'
    #         r"'((?:[^'\\]|\\.)*)'"    # 'single quoted'
    #         r'|"((?:[^"\\]|\\.)*)"'   # "double quoted"
    #         r'|([^\s]+)'              # unquoted value
    #         r')'
    #     )
    #     for m in pattern.finditer(raw):
    #         key = m.group(1)
    #         val = m.group(2) if m.group(2) is not None else \
    #               m.group(3) if m.group(3) is not None else \
    #               m.group(4)
    #         parsed[key] = val
    #     return parsed

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
                    f"Unknown command '{command}'. Valid commands: "
                    "list_protocols, read, create, update_meta, add_steps, edit_steps, "
                    "delete_steps, delete_protocol, list_schedule, get_schedule, edit_schedule, delete_schedule"
                ),
            }))
            return

        try:
            result = await handler(se_interface, kv)
        except Exception as exc:
            result = {"status": "error", "command": command, "reason": str(exc)}

        se_interface.send_message(json.dumps(result, ensure_ascii=False))

    # ══════════════════════════════════════════════════════════════════════════
    # READ commands — Protocol Management
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_list_protocols(self, _si, kv: dict) -> dict:
        PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
        protocols = []
        for toml_file in sorted(PROTOCOLS_DIR.glob("*.toml")):
            try:
                with open(toml_file, "rb") as f:
                    data = tomllib.load(f)
                protocols.append({
                    "protocol_handle_name": data.get("protocol_handle_name", toml_file.stem),
                    "protocol_name": data.get("protocol_name", ""),
                    "protocol_description": data.get("protocol_description", ""),
                })
            except Exception as exc:
                protocols.append({
                    "protocol_handle_name": toml_file.stem,
                    "error": str(exc),
                })
        return {"status": "success", "command": "list_protocols", "protocols": protocols}

    async def _cmd_read(self, _si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        if not handle:
            return {"status": "error", "command": "read",
                    "reason": "Missing 'protocol_handle_name' argument."}
        try:
            data = _load_protocol(handle)
        except FileNotFoundError as exc:
            return {"status": "error", "command": "read",
                    "error_code": "not_found", "reason": str(exc)}
        return {"status": "success", "command": "read", **data}

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands — Protocol Management (permission dialog required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_create(self, si, kv: dict) -> dict:
        # print(kv)
        handle = kv.get("protocol_handle_name")
        if not handle:
            return {"status": "error", "command": "create",
                    "reason": "Missing 'protocol_handle_name' argument."}

        path = _protocol_path(handle)

        # Parse steps JSON
        steps_raw = kv.get("steps", "[]")
        try:
            raw_steps = _parse_json_arg(steps_raw, "steps")
        except ValueError as exc:
            return {"status": "error", "command": "create", "reason": str(exc)}

        # Parse apps_used JSON (may be a JSON array or a bare string)
        apps_raw = kv.get("apps_used", "[]")
        try:
            apps_used = _parse_json_arg(apps_raw, "apps_used") if apps_raw.startswith("[") \
                        else [apps_raw]
        except ValueError:
            apps_used = [apps_raw]

        # Build step list with sequential IDs
        steps = []
        for i, s in enumerate(raw_steps, 1):
            step = {"id": i}
            for field in ["label", "app_command", "prompt", "completion_check_condition"]:
                if field in s:
                    step[field] = s[field]
            steps.append(step)

        data = {
            "protocol_name": kv.get("protocol_name", handle),
            "protocol_handle_name": handle,
            "protocol_description": kv.get("protocol_description", ""),
            "trigger_prompt": kv.get("trigger_prompt", ""),
            "protocol_result": kv.get("protocol_result", ""),
            "apps_used": apps_used,
            "step": steps,
        }

        allowed = self._request_permission("create", {
            "protocol_handle_name": handle,
            "path": str(path),
            "steps_count": len(steps),
        })
        if not allowed:
            return self._denied("create", protocol_handle_name=handle, path=str(path))

        written = _write_protocol(handle, data)
        return self._ok("create", protocol_handle_name=handle, path=str(written))

    async def _cmd_update_meta(self, si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        if not handle:
            return {"status": "error", "command": "update_meta",
                    "reason": "Missing 'protocol_handle_name' argument."}

        try:
            data = _load_protocol(handle)
        except FileNotFoundError as exc:
            return {"status": "error", "command": "update_meta",
                    "error_code": "not_found", "reason": str(exc)}

        meta_fields = ["protocol_name", "protocol_description",
                       "trigger_prompt", "protocol_result", "apps_used"]
        updated_fields = {}
        for field in meta_fields:
            if field in kv:
                val = kv[field]
                if field == "apps_used":
                    try:
                        val = _parse_json_arg(val, field) if val.startswith("[") else [val]
                    except ValueError:
                        val = [val]
                updated_fields[field] = val
                data[field] = val

        if not updated_fields:
            return {"status": "error", "command": "update_meta",
                    "reason": "No metadata fields provided to update."}

        allowed = self._request_permission("update_meta", {
            "protocol_handle_name": handle,
            "fields_to_update": ", ".join(updated_fields.keys()),
        })
        if not allowed:
            return self._denied("update_meta", protocol_handle_name=handle)

        _write_protocol(handle, data)
        return self._ok("update_meta",
                        protocol_handle_name=handle,
                        updated_fields=list(updated_fields.keys()))

    async def _cmd_add_steps(self, si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        steps_raw = kv.get("steps")
        if not handle or not steps_raw:
            return {"status": "error", "command": "add_steps",
                    "reason": "Missing 'protocol_handle_name' or 'steps' argument."}

        try:
            new_steps_data = _parse_json_arg(steps_raw, "steps")
        except ValueError as exc:
            return {"status": "error", "command": "add_steps", "reason": str(exc)}

        try:
            data = _load_protocol(handle)
        except FileNotFoundError as exc:
            return {"status": "error", "command": "add_steps",
                    "error_code": "not_found", "reason": str(exc)}

        existing = data.get("step", [])
        next_id = (max((s["id"] for s in existing), default=0) + 1)

        added = []
        for s in new_steps_data:
            step = {"id": next_id}
            next_id += 1
            for field in ["label", "app_command", "prompt", "completion_check_condition"]:
                if field in s:
                    step[field] = s[field]
            existing.append(step)
            added.append(step["id"])

        data["step"] = existing

        allowed = self._request_permission("add_steps", {
            "protocol_handle_name": handle,
            "steps_to_add": len(added),
            "new_step_ids": str(added),
        })
        if not allowed:
            return self._denied("add_steps", protocol_handle_name=handle)

        _write_protocol(handle, data)
        return self._ok("add_steps",
                        protocol_handle_name=handle,
                        steps_added=added)

    async def _cmd_edit_steps(self, si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        steps_raw = kv.get("steps")
        if not handle or not steps_raw:
            return {"status": "error", "command": "edit_steps",
                    "reason": "Missing 'protocol_handle_name' or 'steps' argument."}

        try:
            edits = _parse_json_arg(steps_raw, "steps")
        except ValueError as exc:
            return {"status": "error", "command": "edit_steps", "reason": str(exc)}

        try:
            data = _load_protocol(handle)
        except FileNotFoundError as exc:
            return {"status": "error", "command": "edit_steps",
                    "error_code": "not_found", "reason": str(exc)}

        existing = {s["id"]: s for s in data.get("step", [])}
        updated_ids = []
        not_found_ids = []

        for edit in edits:
            sid = edit.get("id")
            if sid is None:
                return {"status": "error", "command": "edit_steps",
                        "reason": "Each step in 'steps' must include an 'id' field."}
            if sid not in existing:
                not_found_ids.append(sid)
                continue
            for field in ["label", "app_command", "prompt", "completion_check_condition"]:
                if field in edit:
                    existing[sid][field] = edit[field]
                elif field in edit and edit[field] is None:
                    existing[sid].pop(field, None)
            updated_ids.append(sid)

        if not_found_ids:
            return {"status": "error", "command": "edit_steps",
                    "error_code": "step_not_found",
                    "reason": f"Step IDs not found: {not_found_ids}"}

        data["step"] = list(existing.values())

        allowed = self._request_permission("edit_steps", {
            "protocol_handle_name": handle,
            "step_ids_to_edit": str(updated_ids),
        })
        if not allowed:
            return self._denied("edit_steps", protocol_handle_name=handle)

        _write_protocol(handle, data)
        return self._ok("edit_steps",
                        protocol_handle_name=handle,
                        steps_updated=updated_ids)

    async def _cmd_delete_steps(self, si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        ids_raw = kv.get("step_ids")
        if not handle or not ids_raw:
            return {"status": "error", "command": "delete_steps",
                    "reason": "Missing 'protocol_handle_name' or 'step_ids' argument."}

        try:
            step_ids = _parse_json_arg(ids_raw, "step_ids")
        except ValueError as exc:
            return {"status": "error", "command": "delete_steps", "reason": str(exc)}

        try:
            data = _load_protocol(handle)
        except FileNotFoundError as exc:
            return {"status": "error", "command": "delete_steps",
                    "error_code": "not_found", "reason": str(exc)}

        existing_ids = {s["id"] for s in data.get("step", [])}
        missing = [sid for sid in step_ids if sid not in existing_ids]
        if missing:
            return {"status": "error", "command": "delete_steps",
                    "error_code": "step_not_found",
                    "reason": f"Step IDs not found: {missing}"}

        allowed = self._request_permission("delete_steps", {
            "protocol_handle_name": handle,
            "step_ids_to_delete": str(step_ids),
        })
        if not allowed:
            return self._denied("delete_steps", protocol_handle_name=handle)

        remaining = [s for s in data.get("step", []) if s["id"] not in step_ids]
        data["step"] = _renumber_steps(remaining)
        _write_protocol(handle, data)
        return self._ok("delete_steps",
                        protocol_handle_name=handle,
                        steps_deleted=step_ids)

    async def _cmd_delete_protocol(self, si, kv: dict) -> dict:
        handle = kv.get("protocol_handle_name")
        if not handle:
            return {"status": "error", "command": "delete_protocol",
                    "reason": "Missing 'protocol_handle_name' argument."}

        path = _protocol_path(handle)
        if not path.exists():
            return {"status": "error", "command": "delete_protocol",
                    "error_code": "not_found",
                    "reason": f"Protocol file not found: {path}"}

        allowed = self._request_permission("delete_protocol", {
            "protocol_handle_name": handle,
            "path": str(path),
        })
        if not allowed:
            return self._denied("delete_protocol", protocol_handle_name=handle)

        path.unlink()
        return self._ok("delete_protocol", protocol_handle_name=handle)

    # ══════════════════════════════════════════════════════════════════════════
    # READ commands — Schedule Management
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_list_schedule(self, _si, kv: dict) -> dict:
        entries = _load_schedule_entries()
        return {"status": "success", "command": "list_schedule", "entries": entries}

    async def _cmd_get_schedule(self, _si, kv: dict) -> dict:
        schedule_id = kv.get("schedule_id")
        if not schedule_id:
            return {"status": "error", "command": "get_schedule",
                    "reason": "Missing 'schedule_id' argument."}
        entries = _load_schedule_entries()
        for entry in entries:
            if entry["schedule_id"] == schedule_id:
                return {"status": "success", "command": "get_schedule", **entry}
        return {"status": "error", "command": "get_schedule",
                "error_code": "not_found",
                "reason": f"No schedule entry found for schedule_id: {schedule_id}"}

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands — Schedule Management (permission dialog required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_edit_schedule(self, si, kv: dict) -> dict:
        schedule_id = kv.get("schedule_id")
        new_cron = kv.get("cron_schedule")
        if not schedule_id or not new_cron:
            return {"status": "error", "command": "edit_schedule",
                    "reason": "Missing 'schedule_id' or 'cron_schedule' argument."}

        if not _validate_cron(new_cron):
            return {"status": "error", "command": "edit_schedule",
                    "error_code": "invalid_cron",
                    "reason": f"Invalid cron expression: '{new_cron}'. "
                               "Expected 5 or 6 space-separated fields."}

        entries = _load_schedule_entries()
        target = None
        for entry in entries:
            if entry["schedule_id"] == schedule_id:
                target = entry
                break

        if not target:
            return {"status": "error", "command": "edit_schedule",
                    "error_code": "not_found",
                    "reason": f"No schedule entry found for schedule_id: {schedule_id}"}

        old_cron = target["cron_schedule"]

        allowed = self._request_permission("edit_schedule", {
            "schedule_id": schedule_id,
            "protocol_name": target["protocol_name"],
            "old_cron_schedule": old_cron,
            "new_cron_schedule": new_cron,
        })
        if not allowed:
            return self._denied("edit_schedule", schedule_id=schedule_id,
                                old_cron_schedule=old_cron, new_cron_schedule=new_cron)

        target["cron_schedule"] = new_cron
        _save_schedule_entries(entries)
        return self._ok("edit_schedule", schedule_id=schedule_id,
                        old_cron_schedule=old_cron, new_cron_schedule=new_cron)

    async def _cmd_delete_schedule(self, si, kv: dict) -> dict:
        schedule_id = kv.get("schedule_id")
        if not schedule_id:
            return {"status": "error", "command": "delete",
                    "reason": "Missing 'schedule_id' argument."}

        entries = _load_schedule_entries()
        target = None
        for entry in entries:
            if entry["schedule_id"] == schedule_id:
                target = entry
                break

        if not target:
            return {"status": "error", "command": "delete_schedule",
                    "error_code": "not_found",
                    "reason": f"No schedule entry found for schedule_id: {schedule_id}"}

        allowed = self._request_permission("delete_schedule", {
            "schedule_id": schedule_id,
            "protocol_name": target["protocol_name"],
            "cron_schedule": target["cron_schedule"],
        })
        if not allowed:
            return self._denied("delete_schedule", schedule_id=schedule_id,
                                protocol_name=target["protocol_name"])

        remaining = [e for e in entries if e["schedule_id"] != schedule_id]
        _save_schedule_entries(remaining)
        return self._ok("delete_schedule", schedule_id=schedule_id,
                        protocol_name=target["protocol_name"])


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ProtocolAdminApp()
    app.run_repl()