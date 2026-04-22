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

class soul_engine_interface:
    def __init__(self,args,app_name):
        self.episode_id=args.episode_id
        self.invocation_id=args.invocation_id
        self.app_name=app_name
    def send_message(self,msg):
        sys.stdout.write(f"[#APP_MESSAGE>episode_id:{self.episode_id}|invocation_id:{self.invocation_id}]{msg}\n")
        sys.stdout.flush()
    def send_and_invoke(self,msg):
        sys.stdout.write(f"[#APP_INVOKE>episode_id:{self.episode_id}|invocation_id:{self.invocation_id}]{msg}\n")
        sys.stdout.flush()
        
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


