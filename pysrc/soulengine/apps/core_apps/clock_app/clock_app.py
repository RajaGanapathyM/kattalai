import json
import sys
import asyncio
from datetime import datetime, timedelta

from pathlib import Path
# .parent is 'myapp', .parent.parent is 'apps'
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


def parse_duration(duration_str):
    """
    Parse duration string into seconds.
    Formats supported:
      - 30s          → 30 seconds
      - 5m           → 5 minutes
      - 2h           → 2 hours
      - 2026-03-11 15:30:00  → specific datetime
    Returns (seconds_until, target_datetime) or raises ValueError.
    """
    duration_str = duration_str.strip()
    now = datetime.now()

    # Try datetime format first
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            target = datetime.strptime(duration_str, fmt)
            # If only time provided, assume today
            if fmt in ("%H:%M:%S", "%H:%M"):
                target = target.replace(year=now.year, month=now.month, day=now.day)
            delta = (target - now).total_seconds()
            if delta <= 0:
                raise ValueError(f"Target time '{duration_str}' is in the past.")
            return delta, target
        except ValueError:
            pass

    # Try shorthand: 30s, 5m, 2h
    unit_map = {"s": 1, "m": 60, "h": 3600}
    if duration_str[-1].lower() in unit_map:
        try:
            value = float(duration_str[:-1])
            multiplier = unit_map[duration_str[-1].lower()]
            seconds = value * multiplier
            target = now + timedelta(seconds=seconds)
            return seconds, target
        except ValueError:
            pass

    raise ValueError(
        f"Unrecognised duration format: '{duration_str}'\n"
        "Supported formats: 30s | 5m | 2h | HH:MM | HH:MM:SS | YYYY-MM-DD HH:MM:SS"
    )


async def process_command(se_interface, args):
    """
    Usage:
      alarm_app.py <duration> <message...>
      alarm_app.py now                        → show current time only

    Examples:
      alarm_app.py 30s Take a break
      alarm_app.py 5m  Check the oven
      alarm_app.py 2h  Team standup
      alarm_app.py 15:30 Lunch meeting
      alarm_app.py 2026-03-11 18:00 End of day
    """

    now = datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # No args → show current time + usage
    if not args:
        se_interface.send_message(json.dumps({
            "status": "info",
            "current_time": current_time_str,
            "usage": (
                "alarm_app.py <duration> <message>\n"
                "  duration: 30s | 5m | 2h | HH:MM | YYYY-MM-DD HH:MM:SS\n"
                "  example:  alarm_app.py 5m Take a break"
            )
        }))
        return

    # "now" → just print current time
    if args[0].lower() == "now":
        se_interface.send_message(json.dumps({
            "status": "current_time",
            "current_time": current_time_str
        }))
        return

    # First token = duration, rest = message
    duration_token = args[0]

    # Handle datetime with space: e.g. ["2026-03-11", "18:00", "msg..."]
    # Try combining first two tokens as datetime
    message_start = 1
    if len(args) >= 2:
        combined = f"{args[0]} {args[1]}"
        try:
            seconds, target = parse_duration(combined)
            duration_token = combined
            message_start = 2
        except ValueError:
            # Fall back to single token
            try:
                seconds, target = parse_duration(args[0])
            except ValueError as e:
                se_interface.send_message(json.dumps({
                    "status": "error",
                    "current_time": current_time_str,
                    "message": str(e)
                }))
                return
    else:
        try:
            seconds, target = parse_duration(args[0])
        except ValueError as e:
            se_interface.send_message(json.dumps({
                "status": "error",
                "current_time": current_time_str,
                "message": str(e)
            }))
            return

    alarm_msg = " ".join(args[message_start:]).strip()
    if not alarm_msg:
        se_interface.send_message(json.dumps({
            "status": "error",
            "current_time": current_time_str,
            "message": "No alarm message provided."
        }))
        return

    target_str = target.strftime("%Y-%m-%d %H:%M:%S")

    # Acknowledge the alarm is set
    se_interface.send_message(json.dumps({
        "status": "alarm_set",
        "current_time": current_time_str,
        "fires_at": target_str,
        "in_seconds": round(seconds, 1),
        "message": alarm_msg
    }))

    # Wait, then fire
    await asyncio.sleep(seconds)

    fired_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    se_interface.send_message(json.dumps({
        "status": "alarm_fired",
        "fired_at": fired_at,
        "message": alarm_msg
    }))


if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="SOUL CLOCK")
    soul_app.run_repl(main_fn=process_command)