import json
import sys
import os
import re
import argparse
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Stand-alone helpers (pure functions, no class state needed) ───────────────

def read_lines(target: str):
    p = Path(target)
    if not p.exists():
        raise FileNotFoundError(f"Target not found: {target}")
    if p.is_dir():
        raise IsADirectoryError(f"Target is a directory — use search_recursive: {target}")
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return str(p), f.read().splitlines()


def collect_files(directory: str):
    base = Path(directory)
    if not base.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not base.is_dir():
        raise NotADirectoryError(f"Expected a directory: {directory}")
    for p in sorted(base.rglob("*")):
        if p.is_file():
            yield p


def build_pattern(raw: str, ignore_case: bool, fixed: bool, word: bool):
    pattern = re.escape(raw) if fixed else raw
    if word:
        pattern = rf"\b{pattern}\b"
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(pattern, flags)


def search_lines(compiled, lines, invert=False, max_matches=None):
    results = []
    for idx, line in enumerate(lines, start=1):
        m = compiled.search(line)
        hit = (m is None) if invert else (m is not None)
        if hit:
            results.append({
                "line_number": idx,
                "line": line,
                "match_span": f"{m.start()}:{m.end()}" if (m and not invert) else None,
            })
            if max_matches and len(results) >= max_matches:
                break
    return results


def attach_context(lines, matches, before_n, after_n):
    for m in matches:
        ln = m["line_number"]
        m["context_before"] = lines[max(0, ln - 1 - before_n): ln - 1]
        m["context_after"]  = lines[ln: min(len(lines), ln + after_n)]
    return matches


def compile_or_error(pattern, ignore_case, fixed, word):
    try:
        return build_pattern(pattern, ignore_case, fixed, word), None
    except re.error as e:
        return None, f"Invalid regex pattern: {e}"


def _add_match_flags(p):
    p.add_argument("-i", "--ignore-case", action="store_true")
    p.add_argument("-v", "--invert",      action="store_true")
    p.add_argument("-w", "--word",        action="store_true")
    p.add_argument("-F", "--fixed",       action="store_true")
    p.add_argument("--max",              type=int, default=None, metavar="N")


def _add_count_flags(p):
    p.add_argument("-i", "--ignore-case", action="store_true")
    p.add_argument("-v", "--invert",      action="store_true")
    p.add_argument("-w", "--word",        action="store_true")
    p.add_argument("-F", "--fixed",       action="store_true")


def _add_list_flags(p):
    p.add_argument("-i", "--ignore-case", action="store_true")
    p.add_argument("-w", "--word",        action="store_true")
    p.add_argument("-F", "--fixed",       action="store_true")


def build_parser():
    root = argparse.ArgumentParser(prog="grep_app", add_help=False)
    sub  = root.add_subparsers(dest="command")

    p_search = sub.add_parser("search", add_help=False)
    p_search.add_argument("pattern"); p_search.add_argument("target")
    _add_match_flags(p_search)
    p_search.add_argument("-n", "--line-numbers", action="store_true")
    p_search.add_argument("-C", "--context", type=int, default=0, metavar="N")
    p_search.add_argument("-B", "--before",  type=int, default=0, metavar="N")
    p_search.add_argument("-A", "--after",   type=int, default=0, metavar="N")

    p_rec = sub.add_parser("search_recursive", add_help=False)
    p_rec.add_argument("pattern"); p_rec.add_argument("directory")
    _add_match_flags(p_rec)
    p_rec.add_argument("-n", "--line-numbers", action="store_true")
    p_rec.add_argument("-C", "--context", type=int, default=0, metavar="N")
    p_rec.add_argument("-B", "--before",  type=int, default=0, metavar="N")
    p_rec.add_argument("-A", "--after",   type=int, default=0, metavar="N")

    p_stdin = sub.add_parser("search_stdin", add_help=False)
    p_stdin.add_argument("pattern"); p_stdin.add_argument("input_lines")
    _add_match_flags(p_stdin)
    p_stdin.add_argument("-n", "--line-numbers", action="store_true")

    p_count = sub.add_parser("count", add_help=False)
    p_count.add_argument("pattern"); p_count.add_argument("target")
    _add_count_flags(p_count)

    p_ctx = sub.add_parser("search_with_context", add_help=False)
    p_ctx.add_argument("pattern"); p_ctx.add_argument("target")
    p_ctx.add_argument("before_lines", type=int); p_ctx.add_argument("after_lines", type=int)
    _add_match_flags(p_ctx)

    p_list = sub.add_parser("list_matching_files", add_help=False)
    p_list.add_argument("pattern"); p_list.add_argument("directory")
    _add_list_flags(p_list)

    return root


VALID_COMMANDS = {
    "search", "search_recursive", "search_stdin",
    "count", "search_with_context", "list_matching_files",
}

# ── Command handlers ──────────────────────────────────────────────────────────

def handle_search(opts):
    try:
        path_label, lines = read_lines(opts.target)
    except (FileNotFoundError, IsADirectoryError) as e:
        return {"status": "error", "reason": str(e)}
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    hits = search_lines(compiled, lines, invert=opts.invert, max_matches=opts.max)
    if not hits:
        return {"status": "no_matches", "command": "search", "pattern": opts.pattern, "file": path_label}
    before_n = max(opts.before, opts.context)
    after_n  = max(opts.after,  opts.context)
    if before_n or after_n:
        hits = attach_context(lines, hits, before_n, after_n)
    return {"status": "success", "command": "search", "pattern": opts.pattern,
            "file": path_label, "matches": hits, "match_count": len(hits)}


def handle_search_recursive(opts):
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    try:
        files = list(collect_files(opts.directory))
    except (FileNotFoundError, NotADirectoryError) as e:
        return {"status": "error", "reason": str(e)}
    if not files:
        return {"status": "no_matches", "command": "search_recursive",
                "pattern": opts.pattern, "directory": opts.directory}
    before_n = max(opts.before, opts.context)
    after_n  = max(opts.after,  opts.context)
    grouped, total = [], 0
    for fp in files:
        try:
            _, lines = read_lines(str(fp))
            hits = search_lines(compiled, lines, invert=opts.invert, max_matches=opts.max)
            if hits:
                if before_n or after_n:
                    hits = attach_context(lines, hits, before_n, after_n)
                grouped.append({"file": str(fp), "matches": hits})
                total += len(hits)
                if opts.max and total >= opts.max:
                    break
        except Exception:
            continue
    if not grouped:
        return {"status": "no_matches", "command": "search_recursive",
                "pattern": opts.pattern, "directory": opts.directory}
    return {"status": "success", "command": "search_recursive", "pattern": opts.pattern,
            "directory": opts.directory, "results": grouped,
            "total_matches": total, "files_matched": len(grouped)}


def handle_search_stdin(opts):
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    lines = opts.input_lines.splitlines()
    hits  = search_lines(compiled, lines, invert=opts.invert, max_matches=opts.max)
    if not hits:
        return {"status": "no_matches", "command": "search_stdin", "pattern": opts.pattern}
    return {"status": "success", "command": "search_stdin", "pattern": opts.pattern,
            "matches": hits, "match_count": len(hits)}


def handle_count(opts):
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    target_path = Path(opts.target)
    if not target_path.is_dir():
        try:
            path_label, lines = read_lines(opts.target)
        except (FileNotFoundError, IsADirectoryError) as e:
            return {"status": "error", "reason": str(e)}
        hits = search_lines(compiled, lines, invert=opts.invert)
        return {"status": "success", "command": "count", "pattern": opts.pattern,
                "file": path_label, "match_count": len(hits)}
    try:
        files = list(collect_files(opts.target))
    except (FileNotFoundError, NotADirectoryError) as e:
        return {"status": "error", "reason": str(e)}
    counts = []
    for fp in files:
        try:
            _, lines = read_lines(str(fp))
            hits = search_lines(compiled, lines, invert=opts.invert)
            if hits:
                counts.append({"file": str(fp), "match_count": len(hits)})
        except Exception:
            continue
    if not counts:
        return {"status": "no_matches", "command": "count",
                "pattern": opts.pattern, "target": opts.target}
    return {"status": "success", "command": "count", "pattern": opts.pattern,
            "target": opts.target, "results": counts,
            "total_matches": sum(c["match_count"] for c in counts)}


def handle_search_with_context(opts):
    try:
        path_label, lines = read_lines(opts.target)
    except (FileNotFoundError, IsADirectoryError) as e:
        return {"status": "error", "reason": str(e)}
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    if opts.before_lines < 0 or opts.after_lines < 0:
        return {"status": "error", "reason": "before_lines and after_lines must be >= 0"}
    hits = search_lines(compiled, lines, invert=opts.invert, max_matches=opts.max)
    if not hits:
        return {"status": "no_matches", "command": "search_with_context",
                "pattern": opts.pattern, "file": path_label}
    hits = attach_context(lines, hits, opts.before_lines, opts.after_lines)
    return {"status": "success", "command": "search_with_context",
            "pattern": opts.pattern, "file": path_label,
            "before_lines": opts.before_lines, "after_lines": opts.after_lines,
            "matches": hits, "match_count": len(hits)}


def handle_list_matching_files(opts):
    compiled, err = compile_or_error(opts.pattern, opts.ignore_case, opts.fixed, opts.word)
    if err:
        return {"status": "error", "reason": err}
    try:
        files = list(collect_files(opts.directory))
    except (FileNotFoundError, NotADirectoryError) as e:
        return {"status": "error", "reason": str(e)}
    matching = []
    for fp in files:
        try:
            _, lines = read_lines(str(fp))
            if search_lines(compiled, lines, max_matches=1):
                matching.append(str(fp))
        except Exception:
            continue
    if not matching:
        return {"status": "no_matches", "command": "list_matching_files",
                "pattern": opts.pattern, "directory": opts.directory}
    return {"status": "success", "command": "list_matching_files",
            "pattern": opts.pattern, "directory": opts.directory,
            "file_list": matching, "file_count": len(matching)}


DISPATCH = {
    "search":              handle_search,
    "search_recursive":    handle_search_recursive,
    "search_stdin":        handle_search_stdin,
    "count":               handle_count,
    "search_with_context": handle_search_with_context,
    "list_matching_files": handle_list_matching_files,
}


# ── App class ─────────────────────────────────────────────────────────────────

class GrepApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="Grep App")

    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": "No command provided. Available: " + ", ".join(sorted(VALID_COMMANDS)),
            }))
            return

        command = args[0]
        if command not in VALID_COMMANDS:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"Unknown command: '{command}'",
                "available_commands": sorted(VALID_COMMANDS),
            }))
            return

        parser = build_parser()
        try:
            opts = parser.parse_args(args)
        except SystemExit:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"Invalid arguments for command '{command}': {' '.join(args[1:])}",
            }))
            return

        result = DISPATCH[command](opts)
        se_interface.send_message(json.dumps(result))


if __name__ == "__main__":
    app = GrepApp()
    app.run_repl()