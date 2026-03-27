import json
import time
import sys
import os
import math
import re
import argparse
import asyncio
import shlex
import inspect
from datetime import datetime
from pathlib import Path
import sys
from pathlib import Path
# .parent is 'myapp', .parent.parent is 'apps'
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

script_directory = Path(__file__).parent
# Use a JSON file to persist variables across executions
VARS_FILE = os.path.join(script_directory,"calc_vars.json")

def load_vars():
    if os.path.exists(VARS_FILE):
        with open(VARS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_vars(vars_dict):
    with open(VARS_FILE, "w", encoding="utf-8") as f:
        json.dump(vars_dict, f)

# Basic supported unit conversions
CONVERSIONS = {
    ("km", "miles"): 0.621371,
    ("miles", "km"): 1.60934,
    ("kg", "lbs"): 2.20462,
    ("lbs", "kg"): 0.453592,
    ("hour", "seconds"): 3600,
    ("hours", "seconds"): 3600,
    ("seconds", "hours"): 1/3600
}

async def process_command(se_interface, args):
    if not args:
        se_interface.send_message(json.dumps({
            "status": "error",
            "reason": "No expression or command provided."
        }))
        return
        
    query = " ".join(args).strip()
    variables = load_vars()

    # 1. Handle Listing Variables
    if query.lower() == "vars":
        se_interface.send_message(json.dumps({
            "status": "success",
            "command": "list_variables",
            "variable_map": variables
        }))
        return

    # 2. Handle Clearing Variables
    if query.lower() == "clear vars":
        save_vars({})
        se_interface.send_message(json.dumps({
            "status": "success",
            "command": "clear_variables",
            "confirmation": "All stored variables have been cleared."
        }))
        return

    # 3. Handle Variable Assignment (e.g., "x = 42")
    var_name = None
    if "=" in query and "==" not in query:
        parts = query.split("=", 1)
        var_name = parts[0].strip()
        query = parts[1].strip()

    # 4. Handle Unit Conversions (e.g., "100 km to miles")
    match_convert = re.match(r"([\d\.]+)\s*([a-zA-Z]+)\s+to\s+([a-zA-Z]+)", query.lower())
    if match_convert:
        val_str, src_unit, tgt_unit = match_convert.groups()
        val = float(val_str)
        
        # Handle temp conversions specially
        if src_unit == "fahrenheit" and tgt_unit == "celsius":
            res = (val - 32) * 5/9
        elif src_unit == "celsius" and tgt_unit == "fahrenheit":
            res = (val * 9/5) + 32
        else:
            factor = CONVERSIONS.get((src_unit, tgt_unit))
            if not factor:
                se_interface.send_message(json.dumps({
                    "status": "error", 
                    "reason": f"Unknown or unsupported conversion: {src_unit} to {tgt_unit}"
                }))
                return
            res = val * factor

        se_interface.send_message(json.dumps({
            "status": "success",
            "command": "convert",
            "converted_result": round(res, 4),
            "input": f"{val} {src_unit}",
            "target_unit": tgt_unit
        }))
        return

    # 5. Evaluate Mathematical Expression
    try:
        # Transform percentages: "15% of 200" -> "((15/100)*200)"
        parsed_query = re.sub(r"([\d\.]+)%\s+of\s+([\d\.]+)", r"((\1/100)*\2)", query)
        
        # Transform factorials: "5!" -> "factorial(5)"
        parsed_query = re.sub(r"(\d+)!", r"factorial(\1)", parsed_query)
        
        # Clean up degrees for sin/cos parsing: "sin(90deg)" -> "sin(90)"
        parsed_query = re.sub(r"deg\)", ")", parsed_query)

        # Build a safe evaluation environment
        safe_env = {
            "sqrt": math.sqrt,
            "log": math.log10,
            "factorial": math.factorial,
            "sin": lambda deg: math.sin(math.radians(deg)),
            "cos": lambda deg: math.cos(math.radians(deg)),
            "tan": lambda deg: math.tan(math.radians(deg))
        }
        
        # Inject stored variables (including 'ans') into the environment
        safe_env.update(variables)

        # Evaluate the math safely without __builtins__
        result = eval(parsed_query, {"__builtins__": None}, safe_env)

        # Always store the latest result in 'ans'
        variables["ans"] = result
        if var_name:
            variables[var_name] = result
            
        save_vars(variables)

        if var_name:
            se_interface.send_message(json.dumps({
                "status": "success",
                "command": "store_variable",
                "variable_name": var_name,
                "stored_value": result
            }))
        else:
            se_interface.send_message(json.dumps({
                "status": "success",
                "command": "evaluate",
                "result": result,
                "parsed_expression": parsed_query
            }))

    except Exception as e:
        se_interface.send_message(json.dumps({
            "status": "error",
            "reason": f"Failed to parse or evaluate expression. Error: {str(e)}"
        }))

if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="Calculator App")
    soul_app.run_repl(main_fn=process_command)