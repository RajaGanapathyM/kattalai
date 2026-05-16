# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

"""
App Finder — semantic/keyword search over installed Kattalai app TOML configs.

Scans every *.toml under ./apps, builds a TF-IDF index (sklearn) and ranks
apps by cosine similarity to the query.  Falls back to token-overlap scoring
if sklearn is unavailable.
"""

import json
import sys
from pathlib import Path

# ── stdlib-safe TOML loader (tomllib ≥ 3.11, else tomli) ──────────────────────
try:
    import tomllib  # type: ignore
except ImportError:
    try:
        import tomli as tomllib  # type: ignore  # pip install tomli
    except ImportError:
        tomllib = None  # type: ignore

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

APPS_ROOT = Path("./apps")
DEFAULT_TOP_N = 5
MIN_SCORE = 0.05  # ignore near-zero matches


# ── TOML parsing ───────────────────────────────────────────────────────────────

def _load_toml(path: Path) -> dict:
    if tomllib is None:
        # very minimal fallback parser for key="value" lines only
        result: dict = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("[") and not line.startswith("#"):
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip().strip('"').strip("'")
        return result
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# ── App index ──────────────────────────────────────────────────────────────────

def _collect_apps() -> list[dict]:
    """
    Walk ./apps recursively, parse every *.toml, return a list of dicts with:
        handle_name, app_name, description, commands, toml_path
    """
    records = []
    for toml_path in sorted(APPS_ROOT.rglob("*.toml")):
        try:
            cfg = _load_toml(toml_path)
        except Exception:
            continue

        handle = cfg.get("app_handle_name", "")
        name   = cfg.get("app_name", "")
        guide  = cfg.get("app_usage_guideline", "")

        # collect command names from [[app_command_signatures]]
        sigs = cfg.get("app_command_signatures", [])
        command_names = " ".join(s.get("command", "") for s in sigs) if isinstance(sigs, list) else ""

        if not handle:
            continue  # skip malformed / non-app TOMLs

        # corpus text used for similarity
        corpus = f"{name} {handle} {command_names} {guide}"

        records.append({
            "handle_name": handle,
            "app_name":    name,
            "description": guide.strip(),
            "commands":    command_names.split(),
            "toml_path":   str(toml_path),
            "_corpus":     corpus,
        })
    return records


# ── Similarity engines ─────────────────────────────────────────────────────────

def _tfidf_rank(query: str, records: list[dict], top_n: int) -> list[dict]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    corpus = [r["_corpus"] for r in records]
    vec = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
    )
    tfidf_matrix = vec.fit_transform(corpus)
    q_vec = vec.transform([query])
    scores = cosine_similarity(q_vec, tfidf_matrix).flatten()

    ranked_idx = np.argsort(scores)[::-1]
    results = []
    for i in ranked_idx[:top_n]:
        if scores[i] < MIN_SCORE:
            break
        results.append({**records[i], "_score": float(scores[i])})
    return results


def _keyword_rank(query: str, records: list[dict], top_n: int) -> list[dict]:
    """Token-overlap fallback — no external deps."""
    q_tokens = set(query.lower().split())
    scored = []
    for r in records:
        doc_tokens = set(r["_corpus"].lower().split())
        overlap = len(q_tokens & doc_tokens)
        if overlap:
            scored.append((overlap / max(len(q_tokens), 1), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {**r, "_score": s}
        for s, r in scored[:top_n]
        if s >= MIN_SCORE
    ]


def _rank(query: str, records: list[dict], top_n: int) -> list[dict]:
    try:
        return _tfidf_rank(query, records, top_n)
    except ImportError:
        return _keyword_rank(query, records, top_n)


# ── App class ──────────────────────────────────────────────────────────────────

class AppFinderApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="App Finder App")

    @staticmethod
    def _parse_args(args: list[str]) -> dict:
        parsed: dict = {}
        bare: list[str] = []
        for token in args:
            if "=" in token:
                k, _, v = token.partition("=")
                parsed[k.strip()] = v.strip().strip('"').strip("'")
            else:
                bare.append(token)
        if bare:
            parsed.setdefault("query", " ".join(bare))
        return parsed

    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": "No command given. Valid command: search query=\"<text>\" [top_n=5]",
            }))
            return

        command = args[0].lower()

        if command != "search":
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"Unknown command '{command}'. Only 'search' is supported.",
            }))
            return

        kv    = self._parse_args(args[1:])
        query = kv.get("query", "").strip()
        if not query:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": "Missing 'query' argument.",
            }))
            return

        try:
            top_n = int(kv.get("top_n", DEFAULT_TOP_N))
        except ValueError:
            top_n = DEFAULT_TOP_N

        records = _collect_apps()
        if not records:
            se_interface.send_message(json.dumps({
                "status": "error",
                "reason": f"No app TOMLs found under {APPS_ROOT}",
            }))
            return

        ranked = _rank(query, records, top_n)

        results = [
            {
                "handle_name": r["handle_name"],
                "app_name":    r["app_name"],
                "description": r["description"],
                "commands":    r["commands"],
                "score":       round(r["_score"], 4),
            }
            for r in ranked
        ]

        se_interface.send_message(json.dumps({
            "status":  "success",
            "command": "search",
            "query":   query,
            "total_apps_indexed": len(records),
            "results": results,
        }))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = AppFinderApp()
    app.run_repl()