import json
import sys
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


class ClockApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="SOUL CLOCK")

    # ------------------------------------------------------------------ helpers
    def _parse_duration(self, duration_str: str):
        """
        Parse a duration string into (seconds, target_datetime).
        Supported formats: 30s | 5m | 2h | HH:MM | HH:MM:SS | YYYY-MM-DD HH:MM:SS
        Raises ValueError on unrecognised or past-pointing input.
        """
        duration_str = duration_str.strip()
        now = datetime.now()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
            try:
                target = datetime.strptime(duration_str, fmt)
                if fmt in ("%H:%M:%S", "%H:%M"):
                    target = target.replace(year=now.year, month=now.month, day=now.day)
                delta = (target - now).total_seconds()
                if delta <= 0:
                    raise ValueError(f"Target time '{duration_str}' is in the past.")
                return delta, target
            except ValueError:
                pass

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

    # ------------------------------------------------------------------ main entry
    async def process_command(self, se_interface, args):
        now = datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # No args → show current time + usage
        if not args:
            se_interface.send_message(json.dumps({
                "status": "info",
                "current_time": current_time_str,
                "usage": (
                    "alarm_app <duration> <message>\n"
                    "  duration: 30s | 5m | 2h | HH:MM | YYYY-MM-DD HH:MM:SS\n"
                    "  example:  alarm_app 5m Take a break"
                ),
            }))
            return

        # "now" → just print current time
        if args[0].lower() == "now":
            se_interface.send_message(json.dumps({
                "status": "current_time",
                "current_time": current_time_str,
            }))
            return

        # Try combining first two tokens as a datetime (e.g. "2026-03-11 18:00")
        seconds, target, message_start = None, None, 1
        if len(args) >= 2:
            try:
                seconds, target = self._parse_duration(f"{args[0]} {args[1]}")
                message_start = 2
            except ValueError:
                pass

        if seconds is None:
            try:
                seconds, target = self._parse_duration(args[0])
            except ValueError as e:
                se_interface.send_message(json.dumps({
                    "status": "error",
                    "current_time": current_time_str,
                    "message": str(e),
                }))
                return

        alarm_msg = " ".join(args[message_start:]).strip()
        if not alarm_msg:
            se_interface.send_message(json.dumps({
                "status": "error",
                "current_time": current_time_str,
                "message": "No alarm message provided.",
            }))
            return

        target_str = target.strftime("%Y-%m-%d %H:%M:%S")

        se_interface.send_message(json.dumps({
            "status": "alarm_set",
            "current_time": current_time_str,
            "fires_at": target_str,
            "in_seconds": round(seconds, 1),
            "message": alarm_msg,
        }))

        await asyncio.sleep(seconds)

        se_interface.send_message(json.dumps({
            "status": "alarm_fired",
            "fired_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": alarm_msg,
        }))


if __name__ == "__main__":
    app = ClockApp()
    app.run_repl()