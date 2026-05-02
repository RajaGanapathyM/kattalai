# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import os
import re
from datetime import datetime
from pathlib import Path
import sys

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Optional heavy deps loaded lazily ─────────────────────────────────────────
def _pd():
    try:
        import pandas as pd
        return pd
    except ImportError:
        raise ImportError("pandas is required: pip install pandas openpyxl xlrd odfpy pyarrow")


# ── Constants ──────────────────────────────────────────────────────────────────
MAX_ROWS_DEFAULT = 1000
SUPPORTED_FORMATS = {
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls":  "excel",
    ".ods":  "ods",
    ".csv":  "csv",
    ".tsv":  "tsv",
    ".parquet": "parquet",
    ".json": "json",
}

DIALOG_MESSAGES = {
    "export": "Allow exporting the tabular data to the destination path?",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve(raw: str) -> Path:
    p = Path(os.path.expanduser(raw))
    return p.resolve() if p.is_absolute() else Path.cwd() / p


def _now() -> str:
    return datetime.now().isoformat()


def _detect_format(path: Path) -> str:
    fmt = SUPPORTED_FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension '{path.suffix}'. "
            f"Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    return fmt


def _load_df(path: Path, sheet: str | None, pd):
    """Return (DataFrame, sheet_name_used) for any supported format."""
    fmt = _detect_format(path)

    if fmt == "excel":
        kw = {"sheet_name": sheet or 0}
        df = pd.read_excel(str(path), **kw)
        used_sheet = sheet or _xl_sheet_names(path, pd)[0]
        return df, used_sheet

    if fmt == "ods":
        kw = {"sheet_name": sheet or 0, "engine": "odf"}
        df = pd.read_excel(str(path), **kw)
        used_sheet = sheet or _xl_sheet_names(path, pd)[0]
        return df, used_sheet

    if fmt == "csv":
        df = pd.read_csv(str(path), sep=None, engine="python")
        return df, None

    if fmt == "tsv":
        df = pd.read_csv(str(path), sep="\t")
        return df, None

    if fmt == "parquet":
        df = pd.read_parquet(str(path))
        return df, None

    if fmt == "json":
        df = pd.read_json(str(path))
        return df, None

    raise ValueError(f"Internal: unhandled format '{fmt}'")


def _xl_sheet_names(path: Path, pd) -> list[str]:
    fmt = _detect_format(path)
    if fmt == "excel":
        xl = pd.ExcelFile(str(path))
        return xl.sheet_names
    if fmt == "ods":
        xl = pd.ExcelFile(str(path), engine="odf")
        return xl.sheet_names
    return []


def _rows_to_json(df, max_rows=MAX_ROWS_DEFAULT) -> list[dict]:
    """Convert DataFrame rows to a JSON-safe list of dicts."""
    slice_df = df.head(max_rows) if max_rows else df
    # Replace NaN/NaT with None for JSON
    return json.loads(slice_df.to_json(orient="records", date_format="iso", default_handler=str))


def _filter_cols(df, cols_str: str | None, pd):
    if not cols_str:
        return df
    requested = [c.strip() for c in cols_str.split(",")]
    existing = [c for c in requested if c in df.columns]
    missing  = [c for c in requested if c not in df.columns]
    if missing:
        raise ValueError(f"Column(s) not found: {missing}. Available: {list(df.columns)}")
    return df[existing]


# ── App class ──────────────────────────────────────────────────────────────────

class TabularReaderApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="Tabular Reader App", app_icon="📊")

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

    def _write_ok(self, command: str, **extra) -> dict:
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
        parsed = {}
        for token in args:
            if "=" in token:
                k, _, v = token.partition("=")
                parsed[k.strip()] = v.strip().strip('"').strip("'")
            else:
                parsed.setdefault("_bare", []).append(token)
        return parsed

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
                "Valid: info, sheets, read, head, tail, schema, stats, search, export"
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
    # READ commands
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_info(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("info", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("info", "path_not_found", f"File does not exist: {path}")

        fmt = _detect_format(path)
        result = {
            "format": fmt,
            "size_bytes": path.stat().st_size,
            "path": str(path),
        }

        if fmt in ("excel", "ods"):
            sheet_names = _xl_sheet_names(path, pd)
            result["sheet_names"] = sheet_names
            sheets_info = []
            for name in sheet_names:
                df, _ = _load_df(path, name, pd)
                sheets_info.append({
                    "sheet": name,
                    "rows": len(df),
                    "columns": len(df.columns),
                    "column_names": list(df.columns),
                })
            result["sheets"] = sheets_info
        else:
            df, _ = _load_df(path, None, pd)
            result["rows"] = len(df)
            result["columns"] = len(df.columns)
            result["column_names"] = list(df.columns)

        return self._ok("info", **result)

    async def _cmd_sheets(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("sheets", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("sheets", "path_not_found", f"File does not exist: {path}")

        fmt = _detect_format(path)
        if fmt not in ("excel", "ods"):
            return self._err(
                "sheets", "unsupported_format",
                f"Format '{fmt}' does not support multiple sheets. "
                "Sheet listing is only available for Excel (.xlsx, .xls, .xlsm) and ODS files."
            )

        sheet_names = _xl_sheet_names(path, pd)
        return self._ok("sheets", path=str(path), sheet_names=sheet_names)

    async def _cmd_read(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("read", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("read", "path_not_found", f"File does not exist: {path}")

        df, _ = _load_df(path, kv.get("sheet"), pd)
        df = _filter_cols(df, kv.get("cols"), pd)

        total = len(df)
        start = max(1, int(kv["start"])) if kv.get("start") else 1
        end   = min(total, int(kv["end"])) if kv.get("end") else min(total, MAX_ROWS_DEFAULT)

        if start > total:
            return self._err("read", "range_out_of_bounds",
                             f"start={start} exceeds total rows ({total}).")

        sliced = df.iloc[start - 1: end]
        return self._ok(
            "read",
            path=str(path),
            columns=list(df.columns),
            total_rows=total,
            returned_rows=len(sliced),
            start=start,
            end=end,
            rows=_rows_to_json(sliced, max_rows=None),
        )

    async def _cmd_head(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("head", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("head", "path_not_found", f"File does not exist: {path}")

        n = int(kv.get("n", 10))
        df, _ = _load_df(path, kv.get("sheet"), pd)
        return self._ok(
            "head",
            path=str(path),
            columns=list(df.columns),
            total_rows=len(df),
            n=n,
            rows=_rows_to_json(df.head(n), max_rows=None),
        )

    async def _cmd_tail(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("tail", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("tail", "path_not_found", f"File does not exist: {path}")

        n = int(kv.get("n", 10))
        df, _ = _load_df(path, kv.get("sheet"), pd)
        return self._ok(
            "tail",
            path=str(path),
            columns=list(df.columns),
            total_rows=len(df),
            n=n,
            rows=_rows_to_json(df.tail(n), max_rows=None),
        )

    async def _cmd_schema(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("schema", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("schema", "path_not_found", f"File does not exist: {path}")

        df, _ = _load_df(path, kv.get("sheet"), pd)

        columns = []
        for col in df.columns:
            series = df[col]
            sample = [
                v for v in series.dropna().head(3).tolist()
                if v is not None
            ]
            # Make sample values JSON-safe
            sample = [str(v) if not isinstance(v, (int, float, bool, str)) else v for v in sample]
            columns.append({
                "name": str(col),
                "dtype": str(series.dtype),
                "null_count": int(series.isna().sum()),
                "non_null_count": int(series.notna().sum()),
                "sample_values": sample,
            })

        return self._ok("schema", path=str(path), total_rows=len(df), columns=columns)

    async def _cmd_stats(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        if not raw:
            return self._err("stats", "missing_argument", "Missing 'path' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("stats", "path_not_found", f"File does not exist: {path}")

        df, _ = _load_df(path, kv.get("sheet"), pd)
        numeric_df = df.select_dtypes(include="number")

        if numeric_df.empty:
            return self._ok("stats", path=str(path), total_rows=len(df),
                            message="No numeric columns found.", columns=[])

        desc = numeric_df.describe()
        columns = []
        for col in numeric_df.columns:
            s = desc[col]
            columns.append({
                "name": str(col),
                "count": int(s.get("count", 0)),
                "mean":  round(float(s.get("mean", 0)), 6),
                "std":   round(float(s.get("std",  0)), 6),
                "min":   round(float(s.get("min",  0)), 6),
                "25pct": round(float(s.get("25%",  0)), 6),
                "50pct": round(float(s.get("50%",  0)), 6),
                "75pct": round(float(s.get("75%",  0)), 6),
                "max":   round(float(s.get("max",  0)), 6),
                "nulls": int(numeric_df[col].isna().sum()),
            })

        return self._ok("stats", path=str(path), total_rows=len(df), columns=columns)

    async def _cmd_search(self, _si, kv: dict) -> dict:
        raw = kv.get("path")
        pattern = kv.get("pattern", "")
        if not raw:
            return self._err("search", "missing_argument", "Missing 'path' argument.")
        if not pattern:
            return self._err("search", "missing_argument", "Missing 'pattern' argument.")

        pd = _pd()
        path = _resolve(raw)
        if not path.exists():
            return self._err("search", "path_not_found", f"File does not exist: {path}")

        fmt = _detect_format(path)
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
        matches = []

        if fmt in ("excel", "ods"):
            sheet_names = _xl_sheet_names(path, pd)
            target_sheets = [kv["sheet"]] if kv.get("sheet") else sheet_names
        else:
            target_sheets = [None]

        for sheet_name in target_sheets:
            df, _ = _load_df(path, sheet_name, pd)
            for row_idx, row in df.iterrows():
                for col in df.columns:
                    cell_val = str(row[col]) if row[col] is not None else ""
                    if regex.search(cell_val):
                        matches.append({
                            "sheet":     sheet_name,
                            "row_index": int(row_idx),
                            "column":    str(col),
                            "value":     cell_val,
                        })

        return self._ok("search", path=str(path), pattern=pattern,
                        match_count=len(matches), matches=matches)

    # ══════════════════════════════════════════════════════════════════════════
    # WRITE commands
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_export(self, si, kv: dict) -> dict:
        raw  = kv.get("path")
        dest_raw = kv.get("dest")
        if not raw or not dest_raw:
            return self._err("export", "missing_argument", "Missing 'path' or 'dest' argument.")

        pd = _pd()
        path = _resolve(raw)
        dest = _resolve(dest_raw)

        if not path.exists():
            return self._err("export", "path_not_found", f"Source file does not exist: {path}")

        dest_fmt = SUPPORTED_FORMATS.get(dest.suffix.lower())
        if dest_fmt is None:
            return self._err(
                "export", "unsupported_dest_format",
                f"Unsupported destination format '{dest.suffix}'. "
                f"Supported: {', '.join(SUPPORTED_FORMATS)}"
            )

        if not si.request_permission(
            action="export",
            context={"src": str(path), "dest": str(dest)},
            message=DIALOG_MESSAGES["export"],
        ):
            return self._denied("export", src_path=str(path), dest_path=str(dest))

        df, _ = _load_df(path, kv.get("sheet"), pd)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest_fmt == "csv":
            df.to_csv(str(dest), index=False)
        elif dest_fmt == "tsv":
            df.to_csv(str(dest), sep="\t", index=False)
        elif dest_fmt in ("excel",):
            df.to_excel(str(dest), index=False)
        elif dest_fmt == "ods":
            df.to_excel(str(dest), index=False, engine="odf")
        elif dest_fmt == "parquet":
            df.to_parquet(str(dest), index=False)
        elif dest_fmt == "json":
            df.to_json(str(dest), orient="records", indent=2, date_format="iso",
                       default_handler=str)
        else:
            return self._err("export", "unsupported_dest_format",
                             f"Cannot write to format '{dest_fmt}'.")

        return self._write_ok(
            "export",
            src_path=str(path),
            dest_path=str(dest),
            rows_written=len(df),
        )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = TabularReaderApp()
    app.run_repl()