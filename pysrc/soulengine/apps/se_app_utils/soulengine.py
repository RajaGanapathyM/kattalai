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
        
class soul_engine_app:
    def __init__(self,app_name):
        self.main_fn = None
        self.app_name=app_name
    def parse_line(self,line):
        try:
            tokens = shlex.split(line)
        except ValueError:
            # fallback if quotes are broken
            tokens = line.split()

        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--episode_id")
        parser.add_argument("--invocation_id")

            

        args, remaining = parser.parse_known_args(tokens)

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
            result = await self.main_fn(self.get_interface(args,self.app_name),remaining)

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



    def run_one_shot(self,main_fn):
        try:
            if not inspect.iscoroutinefunction(main_fn):
                raise TypeError("main_fn must be an async function")
            
            
            self.main_fn=main_fn
            
            line = sys.argv
            if len(line)>0:
                line=" ".join(line[1:])
            else:
                line=""
            print(f"Launching App: {self.app_name}")
            asyncio.run(self._process_line(line))
        except Exception as e:
            sys.stdout.write(f"[#APP_ERROR>{str(e)}]")

    def run_repl(self,main_fn):
        try:
            if not inspect.iscoroutinefunction(main_fn):
                raise TypeError("main_fn must be an async function")
            self.main_fn=main_fn
            print(f"Launching App: {self.app_name}")
            asyncio.run(self._loop())
        except Exception as e:
            sys.stdout.write(f"[#APP_ERROR>{str(e)}]")


