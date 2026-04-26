import json
import time
from time import sleep
import sys

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



class soul_engine_interface:
    """
    IPC bridge between a soul_engine app and the Rust runtime.

    All writes go through _send() which:
      1. Checks payload size against _PIPE_INLINE_LIMIT.
      2. If the payload is large, spills it to a temp file and sends a tiny
         envelope pointing to that file — the pipe write always completes
         immediately and flush() fires before Rust's read_line() can block.
      3. Writes the framed line to stdout and flushes explicitly.

    Rust-side contract
    ──────────────────
    Parse the received JSON.  If it contains {"__spilled__": true, "file": "..."}
    read the content from `file` (UTF-8), then delete the file.
    Otherwise use the content directly.
    """

    # Temp files land next to the running script so they stay on the same
    # filesystem / drive letter as the app (important on Windows).
    _spill_dir: Path = Path(sys.argv[0]).resolve().parent / "_se_spill"

    def __init__(self, args, app_name: str):
        self.episode_id    = args.episode_id
        self.invocation_id = args.invocation_id
        self.app_name      = app_name

    # ── internal ──────────────────────────────────────────────────────────────

    def _spill(self, msg: str) -> str:
        """
        If *msg* exceeds _PIPE_INLINE_LIMIT bytes write it to a uniquely-named
        temp file and return a tiny JSON envelope instead:

            {"__spilled__": true, "file": "/abs/path/to/file"}

        Filename format:
            se_spill_<episode_id>_<invocation_id>_<unix_ms>_<uuid4>.json

        Four sources of uniqueness combined:
          - episode_id    : unique per conversation
          - invocation_id : unique per call within a conversation
          - unix_ms       : millisecond timestamp
          - uuid4         : cryptographically random 128-bit token

        This guarantees no two spill files ever collide, even under
        concurrent invocations or rapid repeated calls.
        """
        if len(msg.encode("utf-8")) <= _PIPE_INLINE_LIMIT:
            return msg

        self._spill_dir.mkdir(parents=True, exist_ok=True)

        unique_name = (
            f"se_spill"
            f"_ep{self.episode_id}"
            f"_inv{self.invocation_id}"
            f"_{int(time.time() * 1000)}"   # unix milliseconds
            f"_{uuid.uuid4().hex}"           # 32 hex chars of randomness
            f".json"
        )
        spill_path = self._spill_dir / unique_name
        spill_path.write_text(msg + "\n", encoding="utf-8")

        return json.dumps(
            {"__spilled__": True, "file": str(spill_path)},
            ensure_ascii=False,
        )

    def _send(self, frame_tag: str, msg: str) -> None:
        """
        Core write path shared by send_message and send_and_invoke.

        frame_tag : "#APP_MESSAGE" | "#APP_INVOKE"
        msg       : raw payload string (usually JSON)
        """
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
###################
class soul_engine_app():
    def __init__(self,app_name):
        self.app_name=app_name
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
        return soul_engine_interface(args,app_name)

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


