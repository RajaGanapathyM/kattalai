# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import re
import time
from datetime import datetime
from pathlib import Path
import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


# ── Optional dep ───────────────────────────────────────────────────────────────
def _requests():
    try:
        import requests
        return requests
    except ImportError:
        raise ImportError("requests is required: pip install requests")


# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
MAX_TEXT_BODY_CHARS = 20_000   # truncate large text responses in output
BINARY_TYPES = (
    "image/", "audio/", "video/", "application/octet-stream",
    "application/zip", "application/pdf",
)

DIALOG_MESSAGES = {
    "post":   "Allow sending a POST request to the specified URL?",
    "put":    "Allow sending a PUT request? This will replace the remote resource.",
    "patch":  "Allow sending a PATCH request? This will partially update the remote resource.",
    "delete": "Allow sending a DELETE request? This will permanently remove the remote resource.",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _parse_kv_pairs(raw: str) -> dict:
    """Parse 'key:val,key2:val2' into a dict. Values may contain colons (e.g. Bearer token)."""
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            k, _, v = pair.partition(":")
            result[k.strip()] = v.strip()
    return result


def _is_binary(content_type: str) -> bool:
    ct = content_type.lower()
    return any(ct.startswith(b) for b in BINARY_TYPES)


def _build_response_dict(resp, method: str) -> dict:
    """Convert a requests.Response into a clean serialisable dict."""
    content_type = resp.headers.get("Content-Type", "")
    elapsed_ms = round(resp.elapsed.total_seconds() * 1000, 2)

    base = {
        "status_code": resp.status_code,
        "ok": resp.ok,
        "method": method.upper(),
        "url": resp.url,
        "elapsed_ms": elapsed_ms,
        "content_type": content_type,
        "response_headers": dict(resp.headers),
    }

    if method.upper() == "HEAD":
        return base

    if _is_binary(content_type):
        base["binary_info"] = {
            "size_bytes": len(resp.content),
            "content_type": content_type,
            "note": "Binary content — body not shown.",
        }
        return base

    # Try JSON first
    if "json" in content_type.lower():
        try:
            base["json_body"] = resp.json()
            return base
        except Exception:
            pass

    # Fall back to text
    text = resp.text
    truncated = len(text) > MAX_TEXT_BODY_CHARS
    base["text_body"] = text[:MAX_TEXT_BODY_CHARS] if truncated else text
    if truncated:
        base["text_truncated"] = True
        base["full_size_chars"] = len(text)
    return base


def _drill(data, path: str):
    """Drill into a nested dict/list using dot-separated path."""
    for key in path.split("."):
        if isinstance(data, dict):
            if key not in data:
                raise KeyError(f"Key '{key}' not found. Available: {list(data.keys())}")
            data = data[key]
        elif isinstance(data, list):
            try:
                data = data[int(key)]
            except (ValueError, IndexError):
                raise KeyError(f"Index '{key}' is invalid for a list of length {len(data)}.")
        else:
            raise KeyError(f"Cannot drill into type '{type(data).__name__}' at key '{key}'.")
    return data


# ── App class ──────────────────────────────────────────────────────────────────

class RestApiApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="REST API App", app_icon="🌐")
        self._last_response: dict | None = None
        self._history: list[dict] = []

    # ── Response builders ──────────────────────────────────────────────────────

    def _ok(self, command: str, **extra) -> dict:
        return {"status": "success", "command": command, **extra}

    def _err(self, command: str, code: str, reason: str) -> dict:
        return {"status": "error", "command": command, "error_code": code, "reason": reason}

    def _denied(self, command: str, **extra) -> dict:
        return {
            "status": "denied",
            "command": command,
            "permission_dialog_shown": True,
            "user_confirmed": False,
            "timestamp": _now(),
            **extra,
        }

    def _write_ok(self, command: str, response_data: dict) -> dict:
        return {
            "status": "success",
            "command": command,
            "permission_dialog_shown": True,
            "user_confirmed": True,
            "timestamp": _now(),
            **response_data,
        }

    # ── Argument parser ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_args(args: list[str]) -> dict:
        parsed = {}
        i = 0
        while i < len(args):
            token = args[i]
            if "=" in token:
                k, _, v = token.partition("=")
                # Collect continuation tokens (body JSON may be split by spaces)
                while v.count("{") > v.count("}") or v.count("[") > v.count("]"):
                    i += 1
                    if i >= len(args):
                        break
                    v += " " + args[i]
                parsed[k.strip()] = v.strip().strip('"').strip("'")
            else:
                parsed.setdefault("_bare", []).append(token)
            i += 1
        return parsed

    # ── Request builder ────────────────────────────────────────────────────────

    def _build_request_kwargs(self, kv: dict) -> dict:
        kwargs = {
            "timeout": int(kv.get("timeout", DEFAULT_TIMEOUT)),
            "verify":  kv.get("verify", "true").lower() not in ("false", "0", "no"),
            "allow_redirects": kv.get("follow", "true").lower() not in ("false", "0", "no"),
        }

        if kv.get("headers"):
            kwargs["headers"] = _parse_kv_pairs(kv["headers"])

        if kv.get("params"):
            kwargs["params"] = _parse_kv_pairs(kv["params"])

        if kv.get("auth"):
            user, _, pwd = kv["auth"].partition(":")
            kwargs["auth"] = (user, pwd)

        if kv.get("body"):
            try:
                kwargs["json"] = json.loads(kv["body"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in body=: {exc}")

        if kv.get("form"):
            kwargs["data"] = _parse_kv_pairs(kv["form"])

        return kwargs

    def _record_history(self, method: str, url: str, status_code: int, elapsed_ms: float):
        self._history.append({
            "index": len(self._history) + 1,
            "timestamp": _now(),
            "method": method.upper(),
            "url": url,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
        })

    # ── Dispatcher ─────────────────────────────────────────────────────────────

    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps(self._err(
                "", "no_command", "No command provided."
            )))
            return

        command = args[0].lower()
        kv = self._parse_args(args[1:])

        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            se_interface.send_message(json.dumps(self._err(
                command, "unknown_command",
                f"Unknown command '{command}'. "
                "Valid: get, post, put, patch, delete, head, options, inspect, history, clear"
            )))
            return

        try:
            result = await handler(se_interface, kv)
        except ImportError as exc:
            result = self._err(command, "missing_dependency", str(exc))
        except Exception as exc:
            result = {"status": "error", "command": command, "reason": str(exc)}

        se_interface.send_message(json.dumps(result))

    # ══════════════════════════════════════════════════════════════════════════
    # READ commands  (no confirmation required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_get(self, _si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("get", "missing_argument", "Missing 'url' argument.")

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.get(url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            return self._err("get", "connection_error", str(exc))
        except requests.exceptions.Timeout:
            return self._err("get", "timeout", f"Request timed out after {kwargs['timeout']}s.")
        except requests.exceptions.RequestException as exc:
            return self._err("get", "request_error", str(exc))

        data = _build_response_dict(resp, "GET")
        self._last_response = data
        self._record_history("GET", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._ok("get", **data)

    async def _cmd_head(self, _si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("head", "missing_argument", "Missing 'url' argument.")

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.head(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            return self._err("head", "request_error", str(exc))

        data = _build_response_dict(resp, "HEAD")
        self._last_response = data
        self._record_history("HEAD", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._ok("head", **data)

    async def _cmd_options(self, _si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("options", "missing_argument", "Missing 'url' argument.")

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.options(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            return self._err("options", "request_error", str(exc))

        data = _build_response_dict(resp, "OPTIONS")
        allow_header = resp.headers.get("Allow", "")
        data["allowed_methods"] = [m.strip() for m in allow_header.split(",") if m.strip()]
        self._last_response = data
        self._record_history("OPTIONS", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._ok("options", **data)

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands  (confirmation required)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_post(self, si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("post", "missing_argument", "Missing 'url' argument.")

        if not si.request_permission(
            action="post",
            context={"url": url, "has_body": bool(kv.get("body")), "has_form": bool(kv.get("form"))},
            message=DIALOG_MESSAGES["post"],
        ):
            return self._denied("post", url=url)

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.post(url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            return self._err("post", "connection_error", str(exc))
        except requests.exceptions.Timeout:
            return self._err("post", "timeout", f"Request timed out after {kwargs['timeout']}s.")
        except requests.exceptions.RequestException as exc:
            return self._err("post", "request_error", str(exc))

        data = _build_response_dict(resp, "POST")
        self._last_response = data
        self._record_history("POST", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._write_ok("post", data)

    async def _cmd_put(self, si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("put", "missing_argument", "Missing 'url' argument.")

        if not si.request_permission(
            action="put",
            context={"url": url},
            message=DIALOG_MESSAGES["put"],
        ):
            return self._denied("put", url=url)

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.put(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            return self._err("put", "request_error", str(exc))

        data = _build_response_dict(resp, "PUT")
        self._last_response = data
        self._record_history("PUT", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._write_ok("put", data)

    async def _cmd_patch(self, si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("patch", "missing_argument", "Missing 'url' argument.")

        if not si.request_permission(
            action="patch",
            context={"url": url},
            message=DIALOG_MESSAGES["patch"],
        ):
            return self._denied("patch", url=url)

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.patch(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            return self._err("patch", "request_error", str(exc))

        data = _build_response_dict(resp, "PATCH")
        self._last_response = data
        self._record_history("PATCH", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._write_ok("patch", data)

    async def _cmd_delete(self, si, kv: dict) -> dict:
        url = kv.get("url")
        if not url:
            return self._err("delete", "missing_argument", "Missing 'url' argument.")

        if not si.request_permission(
            action="delete",
            context={"url": url},
            message=DIALOG_MESSAGES["delete"],
        ):
            return self._denied("delete", url=url)

        requests = _requests()
        kwargs = self._build_request_kwargs(kv)

        try:
            resp = requests.delete(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            return self._err("delete", "request_error", str(exc))

        data = _build_response_dict(resp, "DELETE")
        self._last_response = data
        self._record_history("DELETE", resp.url, resp.status_code,
                             round(resp.elapsed.total_seconds() * 1000, 2))
        return self._write_ok("delete", data)

    # ══════════════════════════════════════════════════════════════════════════
    # SESSION commands
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_inspect(self, _si, kv: dict) -> dict:
        if self._last_response is None:
            return self._err("inspect", "no_response",
                             "No response cached. Make a request first.")

        drill_path = kv.get("path")
        if drill_path:
            try:
                data = _drill(self._last_response, drill_path)
                return self._ok("inspect", path=drill_path, data=data)
            except KeyError as exc:
                return self._err("inspect", "key_not_found", str(exc))

        return self._ok("inspect", data=self._last_response)

    async def _cmd_history(self, _si, kv: dict) -> dict:
        return self._ok("history", total=len(self._history), entries=self._history)

    async def _cmd_clear(self, _si, kv: dict) -> dict:
        count = len(self._history)
        self._history.clear()
        self._last_response = None
        return self._ok("clear", cleared_entries=count,
                        message="Session history and cached response cleared.")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = RestApiApp()
    app.run_repl()