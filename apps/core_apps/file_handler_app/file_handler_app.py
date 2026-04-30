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
import tkinter as tk
from tkinter import ttk

import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


# ── Constants ──────────────────────────────────────────────────────────────────
# Maximum file size allowed for a full read without a range (10 MB).
# Files larger than this require the caller to supply start= / end= line args.
READ_SIZE_LIMIT_BYTES = 10 * 1024 * 1024  # 10 MB

# Encodings tried in order when UTF-8 decoding fails.
FALLBACK_ENCODINGS = ["latin-1", "cp1252", "utf-16"]

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


def _read_text(path: Path) -> tuple[str, str]:
    """
    Read *path* as text.  Returns (content, encoding_used).
    Tries UTF-8 first, then falls back through FALLBACK_ENCODINGS.
    Raises ValueError if no encoding succeeds.
    """
    for enc in ["utf-8"] + FALLBACK_ENCODINGS:
        try:
            content = path.read_text(encoding=enc)
            return content, enc
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError(
        f"Could not decode '{path}' as text with any supported encoding "
        f"(tried utf-8, {', '.join(FALLBACK_ENCODINGS)}). "
        "The file may be binary."
    )


class FileHandlerApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="File Handler App")

    # ── Permission dialog ──────────────────────────────────────────────────────
    def _request_permission(self, _si, command: str, context: dict) -> bool:
        """
        Opens a blocking tkinter dialog.
        Returns True if the user clicked Allow, False if Deny / closed the window.
        """
        result = {"allowed": False}

        root = tk.Tk()
        root.title("File Operation Permission")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")

        # Centre on screen
        root.update_idletasks()
        w, h = 460, 260
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Icon row ──────────────────────────────────────────────────────────
        icon_frame = tk.Frame(root, bg="#1e1e2e")
        icon_frame.pack(fill="x", padx=20, pady=(18, 0))

        icon_lbl = tk.Label(icon_frame, text="⚠", font=("Segoe UI", 26),
                            fg="#f38ba8", bg="#1e1e2e")
        icon_lbl.pack(side="left")

        title_lbl = tk.Label(icon_frame,
                             text=f"Permission Required — {command.upper()}",
                             font=("Segoe UI", 11, "bold"),
                             fg="#cdd6f4", bg="#1e1e2e")
        title_lbl.pack(side="left", padx=(10, 0), pady=4)

        # ── Message ───────────────────────────────────────────────────────────
        msg_lbl = tk.Label(root, text=DIALOG_MESSAGES[command],
                           font=("Segoe UI", 10), fg="#a6adc8", bg="#1e1e2e",
                           wraplength=420, justify="left")
        msg_lbl.pack(fill="x", padx=20, pady=(8, 0))

        # ── Context details ───────────────────────────────────────────────────
        detail_frame = tk.Frame(root, bg="#313244", highlightthickness=0)
        detail_frame.pack(fill="x", padx=20, pady=10)

        for key, val in context.items():
            row = tk.Frame(detail_frame, bg="#313244")
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{key}:", font=("Consolas", 9, "bold"),
                     fg="#89b4fa", bg="#313244", width=12, anchor="w").pack(side="left")
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
                          "Valid commands: list, stat, read, search, new, mkdir, edit, "
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

    async def _cmd_read(self, _si, kv: dict) -> dict:
        """
        Read a file as text and return its content.

        Optional args:
          start=<int>  – 1-based first line to return (default: 1)
          end=<int>    – 1-based last line to return, inclusive (default: last line)

        Without start/end the whole file is returned, subject to READ_SIZE_LIMIT_BYTES.
        With start/end only the requested slice is decoded (no size cap).
        """
        raw = kv.get("path")
        if not raw:
            return {"status": "error", "command": "read", "reason": "Missing 'path' argument."}

        path = _resolve(raw)

        if not path.exists():
            return {"status": "error", "command": "read", "error_code": "path_not_found",
                    "reason": f"File does not exist: {path}"}
        if path.is_dir():
            return {"status": "error", "command": "read", "error_code": "is_directory",
                    "reason": "Path is a directory. Use 'list' to inspect directories."}

        size = path.stat().st_size

        # Parse optional line-range args
        start_arg = kv.get("start")
        end_arg = kv.get("end")
        has_range = start_arg is not None or end_arg is not None

        if not has_range and size > READ_SIZE_LIMIT_BYTES:
            return {
                "status": "error",
                "command": "read",
                "error_code": "file_too_large",
                "reason": (
                    f"File is {size:,} bytes which exceeds the {READ_SIZE_LIMIT_BYTES:,}-byte "
                    "limit for a full read. Supply start= and end= line numbers to read a slice."
                ),
                "size": size,
                "path": str(path),
            }

        try:
            content, encoding = _read_text(path)
        except ValueError as exc:
            return {"status": "error", "command": "read", "error_code": "binary_file",
                    "reason": str(exc), "path": str(path)}

        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)

        if has_range:
            try:
                start = max(1, int(start_arg)) if start_arg is not None else 1
                end = min(total_lines, int(end_arg)) if end_arg is not None else total_lines
            except ValueError:
                return {"status": "error", "command": "read",
                        "reason": "start= and end= must be integers."}

            if start > total_lines:
                return {
                    "status": "error", "command": "read",
                    "error_code": "range_out_of_bounds",
                    "reason": f"start={start} exceeds total lines ({total_lines}).",
                    "total_lines": total_lines,
                }

            sliced = all_lines[start - 1: end]
            content = "".join(sliced)
            returned_lines = len(sliced)
        else:
            start = 1
            end = total_lines
            returned_lines = total_lines

        return {
            "status": "success",
            "command": "read",
            "path": str(path),
            "encoding": encoding,
            "size": size,
            "total_lines": total_lines,
            "start": start,
            "end": end,
            "lines_returned": returned_lines,
            "content": content,
        }

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