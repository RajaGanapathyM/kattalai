# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import os
import shutil
import glob as glob_module
import re
from datetime import datetime
from pathlib import Path

import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


# ── Dialog messages mirrored from TOML ────────────────────────────────────────
DIALOG_MESSAGES = {
    "new":    "Allow creating a new file at the specified path?",
    "mkdir":  "Allow creating a new directory at the specified path?",
    "edit":   "Allow overwriting the existing content of this file?",
    "append": "Allow appending new content to this file?",
    "copy":   "Allow copying the file to the destination path?",
    "move":   "Allow moving the file to the destination path? The source will no longer exist.",
    "rename": "Allow renaming this file or directory?",
    "delete": "Allow permanently deleting this file? This cannot be undone.",
    "rmdir":  "Allow deleting this directory and all its contents? This cannot be undone.",
}


def _resolve(raw_path: str) -> Path:
    """Expand ~, resolve relative paths to cwd."""
    p = Path(os.path.expanduser(raw_path))
    return p.resolve() if p.is_absolute() else Path.cwd() / p


def _stat_dict(path: Path) -> dict:
    st = path.stat()
    return {
        "path": str(path),
        "size": st.st_size,
        "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
        "created_at": datetime.fromtimestamp(st.st_ctime).isoformat(),
        "permissions": oct(st.st_mode)[-3:],
    }


def _now() -> str:
    return datetime.now().isoformat()


class FileHandlerApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="File Handler App")

    # ── Permission dialog ──────────────────────────────────────────────────────
    def _request_permission(self, se_interface, command: str, context: dict) -> bool:
        """
        Sends a structured permission_dialog message through se_interface,
        then blocks on stdin for the user's yes/no reply.

        Returns True if the user allowed the operation, False otherwise.
        """
        dialog_payload = json.dumps({
            "type": "permission_dialog",
            "command": command,
            "message": DIALOG_MESSAGES[command],
            "context": context,
            "prompt": "Type 'yes' to allow or 'no' to deny: ",
        })
        se_interface.send_message(dialog_payload)

        try:
            raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            raw = "no"

        return raw in ("yes", "y", "allow", "ok")

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
        Parses key=value tokens.  Values may be quoted or unquoted.
        Remaining bare tokens are treated as the 'pattern' value.
        """
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
                "reason": "No command provided.",
            }))
            return

        command = args[0].lower()
        kv = self._parse_args(args[1:])

        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"Unknown command '{command}'. "
                          "Valid commands: list, stat, search, new, mkdir, edit, "
                          "append, copy, move, rename, delete, rmdir",
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

    async def _cmd_list(self, _si, kv: dict) -> dict:
        raw = kv.get("path", ".")

        # Glob pattern
        if raw.startswith("glob:"):
            pattern = raw[5:].strip()
            matches = glob_module.glob(pattern, recursive=True)
            entries = []
            for m in matches:
                p = Path(m)
                entries.append({
                    "name": p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": p.stat().st_size if p.is_file() else None,
                })
            return {"status": "success", "command": "list", "entries": entries}

        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "list", "error_code": "path_not_found",
                    "reason": f"Path does not exist: {path}"}
        if not path.is_dir():
            return {"status": "error", "command": "list", "error_code": "not_a_directory",
                    "reason": f"Path is not a directory: {path}"}

        entries = []
        for child in sorted(path.iterdir()):
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            })
        return {"status": "success", "command": "list", "path": str(path), "entries": entries}

    async def _cmd_stat(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return {"status": "error", "command": "stat", "reason": "Missing 'path' argument."}
        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "stat", "error_code": "path_not_found",
                    "reason": f"Path does not exist: {path}"}
        return {"status": "success", "command": "stat", **_stat_dict(path)}

    async def _cmd_search(self, _si, kv: dict) -> dict:
        raw_path = kv.get("path", ".")
        pattern = kv.get("pattern", "")
        if not pattern:
            return {"status": "error", "command": "search", "reason": "Missing 'pattern' argument."}

        path = _resolve(raw_path)
        if not path.exists():
            return {"status": "error", "command": "search", "error_code": "path_not_found",
                    "reason": f"Path does not exist: {path}"}

        matches = []
        search_regex = re.compile(re.escape(pattern), re.IGNORECASE)
        files_to_search = [path] if path.is_file() else path.rglob("*")

        for fp in files_to_search:
            if not isinstance(fp, Path):
                fp = Path(fp)
            if not fp.is_file():
                continue
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                for lineno, line in enumerate(lines, 1):
                    if search_regex.search(line):
                        matches.append({
                            "path": str(fp),
                            "line_number": lineno,
                            "snippet": line.strip(),
                        })
            except Exception:
                pass  # skip binary / unreadable files

        return {"status": "success", "command": "search", "pattern": pattern, "matches": matches}

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands (permission dialog required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_new(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        content = kv.get("content", "")
        if not raw:
            return {"status": "error", "command": "new", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        allowed = self._request_permission(si, "new", {"path": str(path)})
        if not allowed:
            return self._denied("new", path=str(path))

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self._ok("new", path=str(path))

    async def _cmd_mkdir(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return {"status": "error", "command": "mkdir", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        allowed = self._request_permission(si, "mkdir", {"path": str(path)})
        if not allowed:
            return self._denied("mkdir", path=str(path))

        path.mkdir(parents=True, exist_ok=True)
        return self._ok("mkdir", path=str(path))

    async def _cmd_edit(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        content = kv.get("content", "")
        if not raw:
            return {"status": "error", "command": "edit", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "edit", "error_code": "path_not_found",
                    "reason": f"File does not exist: {path}"}

        allowed = self._request_permission(si, "edit", {"path": str(path)})
        if not allowed:
            return self._denied("edit", path=str(path))

        path.write_text(content, encoding="utf-8")
        return self._ok("edit", path=str(path))

    async def _cmd_append(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        content = kv.get("content", "")
        if not raw:
            return {"status": "error", "command": "append", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "append", "error_code": "path_not_found",
                    "reason": f"File does not exist: {path}"}

        allowed = self._request_permission(si, "append", {"path": str(path)})
        if not allowed:
            return self._denied("append", path=str(path))

        with path.open("a", encoding="utf-8") as f:
            f.write(content)
        return self._ok("append", path=str(path))

    async def _cmd_copy(self, si, kv: dict) -> dict:
        src_raw = kv.get("src") or kv.get("src_path")
        dest_raw = kv.get("dest") or kv.get("dest_path")
        if not src_raw or not dest_raw:
            return {"status": "error", "command": "copy",
                    "reason": "Missing 'src' or 'dest' argument."}

        src = _resolve(src_raw)
        dest = _resolve(dest_raw)

        if not src.exists():
            return {"status": "error", "command": "copy", "error_code": "path_not_found",
                    "reason": f"Source does not exist: {src}"}

        allowed = self._request_permission(si, "copy", {"src": str(src), "dest": str(dest)})
        if not allowed:
            return self._denied("copy", src_path=str(src), dest_path=str(dest))

        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
        else:
            shutil.copy2(str(src), str(dest))
        return self._ok("copy", src_path=str(src), dest_path=str(dest))

    async def _cmd_move(self, si, kv: dict) -> dict:
        src_raw = kv.get("src") or kv.get("src_path")
        dest_raw = kv.get("dest") or kv.get("dest_path")
        if not src_raw or not dest_raw:
            return {"status": "error", "command": "move",
                    "reason": "Missing 'src' or 'dest' argument."}

        src = _resolve(src_raw)
        dest = _resolve(dest_raw)

        if not src.exists():
            return {"status": "error", "command": "move", "error_code": "path_not_found",
                    "reason": f"Source does not exist: {src}"}

        allowed = self._request_permission(si, "move", {"src": str(src), "dest": str(dest)})
        if not allowed:
            return self._denied("move", src_path=str(src), dest_path=str(dest))

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return self._ok("move", src_path=str(src), dest_path=str(dest))

    async def _cmd_rename(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        new_name = kv.get("new_name")
        if not raw or not new_name:
            return {"status": "error", "command": "rename",
                    "reason": "Missing 'path' or 'new_name' argument."}

        old_path = _resolve(raw)
        new_path = old_path.parent / new_name

        if not old_path.exists():
            return {"status": "error", "command": "rename", "error_code": "path_not_found",
                    "reason": f"Path does not exist: {old_path}"}

        allowed = self._request_permission(si, "rename",
                                           {"old_path": str(old_path), "new_path": str(new_path)})
        if not allowed:
            return self._denied("rename", old_path=str(old_path), new_path=str(new_path))

        old_path.rename(new_path)
        return self._ok("rename", old_path=str(old_path), new_path=str(new_path))

    async def _cmd_delete(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return {"status": "error", "command": "delete", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "delete", "error_code": "path_not_found",
                    "reason": f"File does not exist: {path}"}
        if path.is_dir():
            return {"status": "error", "command": "delete", "error_code": "is_directory",
                    "reason": f"Path is a directory. Use 'rmdir' to remove directories."}

        allowed = self._request_permission(si, "delete", {"path": str(path)})
        if not allowed:
            return self._denied("delete", path=str(path))

        path.unlink()
        return self._ok("delete", path=str(path))

    async def _cmd_rmdir(self, si, kv: dict) -> dict:
        raw = kv.get("path")
        recursive = kv.get("recursive", "false").lower() in ("true", "1", "yes")
        if not raw:
            return {"status": "error", "command": "rmdir", "reason": "Missing 'path' argument."}

        path = _resolve(raw)
        if not path.exists():
            return {"status": "error", "command": "rmdir", "error_code": "path_not_found",
                    "reason": f"Directory does not exist: {path}"}
        if not path.is_dir():
            return {"status": "error", "command": "rmdir", "error_code": "not_a_directory",
                    "reason": f"Path is not a directory: {path}"}

        # Count files before deletion for the response
        files_removed = sum(1 for _ in path.rglob("*") if _.is_file())

        allowed = self._request_permission(si, "rmdir",
                                           {"path": str(path), "recursive": recursive,
                                            "files_that_will_be_removed": files_removed})
        if not allowed:
            return self._denied("rmdir", path=str(path))

        if recursive:
            shutil.rmtree(str(path))
        else:
            try:
                path.rmdir()  # fails if not empty
            except OSError:
                return {"status": "error", "command": "rmdir", "error_code": "directory_not_empty",
                        "reason": "Directory is not empty. Pass recursive=true to force removal."}

        return self._ok("rmdir", path=str(path), files_removed=files_removed)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = FileHandlerApp()
    app.run_repl()