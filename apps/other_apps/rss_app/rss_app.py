"""
Soul RSS App  —  REPL
─────────────────────────────────────────
Subscribe to RSS / Atom feeds, poll for new items, search cached content.
All subscriptions and item caches are scoped to the episode_id supplied by
the Soul Engine runtime, so each conversation episode has its own independent
feed list and seen-state.

Auto-refresh
────────────
A background asyncio task wakes every 60 seconds, scans the DB for any feed
whose refresh window has elapsed, and calls se_interface.send_and_invoke()
so the Rust runtime schedules a follow-up poll invocation automatically —
no manual 'poll' command needed.

Soul Engine Commands
────────────────────
  subscribe <url> <label> [refresh=<minutes>]   → add/update a subscription
  unsubscribe <label>                            → remove sub + clear cache
  list                                           → list subs for this episode
  check [<label>]                                → new items only (respects refresh rate)
  fetch [<label>]                                → force-fetch ignoring refresh rate
  poll                                           → check ALL subscriptions
  peek [<label>] [n=<count>]                     → view unseen items without marking seen
  items [<label>] [n=<count>]                    → recent cached items (all, incl. seen)
  search <query> [in=<label>] [n=<count>]        → BM25 / keyword search cached items
  digest [<label>] [n=<count>]                   → compact title+link digest for briefings
  clear_seen [<label>]                           → reset seen flags (re-report on next check)
  status                                         → timing / count summary per feed
  help                                           → show command reference

Dependencies
────────────
  pip install feedparser rank_bm25
  rank_bm25 is optional — falls back to substring match if absent.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── path bootstrap ─────────────────────────────────────────────────────────────
_APPS_PATH = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_APPS_PATH))
from se_app_utils.soulengine import soul_engine_app  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    import feedparser
    FEEDPARSER_OK = True
except ImportError:
    FEEDPARSER_OK = False
    print("[RSS] ⚠  feedparser not installed. Run: pip install feedparser", flush=True)

try:
    from rank_bm25 import BM25Okapi
    BM25_OK = True
except ImportError:
    BM25_OK = False
    print("[RSS] ℹ  rank_bm25 not installed — using substring search fallback.", flush=True)

# ── storage ────────────────────────────────────────────────────────────────────
_DB_DIR  = Path(__file__).resolve().parent / "data"
_DB_PATH = _DB_DIR / "rss.db"
_db_lock = threading.Lock()

# seconds to wait for a single feed HTTP request before giving up
_FETCH_TIMEOUT_S = 30

# how often (seconds) the background task wakes to check for due feeds
_AUTO_REFRESH_INTERVAL_S = 60


# ══════════════════════════════════════════════════════════════════════════════
#  Database helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    with _db_lock:
        conn = _get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id       TEXT    NOT NULL,
                    label            TEXT    NOT NULL,
                    url              TEXT    NOT NULL,
                    refresh_minutes  INTEGER NOT NULL DEFAULT 60,
                    last_fetched_at  REAL,
                    created_at       REAL    NOT NULL,
                    UNIQUE(episode_id, label)
                );

                CREATE TABLE IF NOT EXISTS items (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id  TEXT    NOT NULL,
                    feed_label  TEXT    NOT NULL,
                    feed_url    TEXT    NOT NULL,
                    guid        TEXT    NOT NULL,
                    title       TEXT,
                    link        TEXT,
                    summary     TEXT,
                    pub_date    TEXT,
                    cached_at   REAL    NOT NULL,
                    seen        INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(episode_id, feed_label, guid)
                );

                CREATE INDEX IF NOT EXISTS idx_items_ep_label
                    ON items(episode_id, feed_label);
                CREATE INDEX IF NOT EXISTS idx_items_unseen
                    ON items(episode_id, feed_label, seen);
                CREATE INDEX IF NOT EXISTS idx_items_cached
                    ON items(episode_id, cached_at DESC);
            """)
            conn.commit()
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Tiny HTML stripper (no extra dep)
# ══════════════════════════════════════════════════════════════════════════════

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ══════════════════════════════════════════════════════════════════════════════
#  RSSApp
# ══════════════════════════════════════════════════════════════════════════════

class RSSApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="RSS App", app_icon="📡")
        _init_db()

        # episode_id → most-recent soul_engine_interface for that episode.
        # The background task uses these to fire send_and_invoke.
        self._active_interfaces: dict[str, object] = {}

        # Will hold the background asyncio.Task once the event loop starts.
        self._bg_task: asyncio.Task | None = None

        print("[RSS] ✓ RSSApp initialised", flush=True)

    # ── dispatcher ────────────────────────────────────────────────────────────

    async def process_command(self, se_interface, args):
        # Always refresh the cached interface so the background task has the
        # latest invocation_id for this episode.
        self._active_interfaces[se_interface.episode_id] = se_interface

        cmd  = (args[0].lower().strip() if args else "help")
        rest = args[1:] if len(args) > 1 else []

        # split key=value kwargs vs positional tokens
        kwargs:     dict[str, str] = {}
        positional: list[str]      = []
        for tok in rest:
            if "=" in tok and tok.split("=", 1)[0].replace("_", "").isalpha():
                k, v = tok.split("=", 1)
                kwargs[k.lower()] = v
            else:
                positional.append(tok)

        episode_id = se_interface.episode_id

        _dispatch = {
            "subscribe":   self._cmd_subscribe,
            "sub":         self._cmd_subscribe,
            "unsubscribe": self._cmd_unsubscribe,
            "unsub":       self._cmd_unsubscribe,
            "list":        self._cmd_list,
            "ls":          self._cmd_list,
            "check":       self._cmd_check,
            "fetch":       self._cmd_fetch,
            "poll":        self._cmd_poll,
            "peek":        self._cmd_peek,
            "items":       self._cmd_items,
            "recent":      self._cmd_items,
            "search":      self._cmd_search,
            "digest":      self._cmd_digest,
            "clear_seen":  self._cmd_clear_seen,
            "status":      self._cmd_status,
            "help":        self._cmd_help,
        }

        handler = _dispatch.get(cmd)
        if handler is None:
            se_interface.send_message(json.dumps({
                "status":  "error",
                "message": f"Unknown command '{cmd}'. Send 'help' for a command list.",
            }))
            return

        try:
            await handler(se_interface, episode_id, positional, kwargs)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            se_interface.send_message(json.dumps({
                "status":  "error",
                "message": f"'{cmd}' failed: {str(exc)[:300]}",
            }))

    # ══════════════════════════════════════════════════════════════════════════
    #  Auto-refresh background task
    # ══════════════════════════════════════════════════════════════════════════

    async def _auto_refresh_loop(self) -> None:
        """
        Wakes every _AUTO_REFRESH_INTERVAL_S seconds.
        For every feed whose refresh window has elapsed, fires send_and_invoke
        so the Rust runtime schedules a follow-up poll invocation for that
        episode — completely hands-free, no agent command needed.
        """
        print(
            f"[RSS] ✓ auto-refresh background task started "
            f"(check interval: {_AUTO_REFRESH_INTERVAL_S}s)",
            flush=True,
        )
        while True:
            await asyncio.sleep(_AUTO_REFRESH_INTERVAL_S)
            try:
                await self._trigger_due_feeds()
            except Exception:
                import traceback
                traceback.print_exc()

    async def _trigger_due_feeds(self) -> None:
        """
        Scans the DB for subscriptions whose refresh window has elapsed,
        groups them by episode, and calls send_and_invoke on the cached
        interface for each episode that has an active interface in this
        process lifetime.
        """
        now = time.time()

        with _db_lock:
            conn = _get_conn()
            try:
                due_rows = conn.execute("""
                    SELECT episode_id,
                           label,
                           url,
                           refresh_minutes,
                           last_fetched_at
                    FROM   subscriptions
                    WHERE  last_fetched_at IS NULL
                       OR  (? - last_fetched_at) >= (refresh_minutes * 60)
                """, (now,)).fetchall()
            finally:
                conn.close()

        if not due_rows:
            return

        # group overdue labels per episode
        by_episode: dict[str, list[str]] = {}
        for row in due_rows:
            by_episode.setdefault(row["episode_id"], []).append(row["label"])

        for episode_id, labels in by_episode.items():
            se = self._active_interfaces.get(episode_id)
            if se is None:
                # Episode never touched this process instance — skip silently.
                # It will be picked up once the episode sends any command.
                continue

            print(
                f"[RSS] ⏰ auto-refresh trigger  "
                f"episode={episode_id}  feeds={labels}",
                flush=True,
            )
            se.send_and_invoke(json.dumps({
                "status":     "auto_refresh_trigger",
                "action":     "poll",
                "episode_id": episode_id,
                "feeds_due":  labels,
                "message": (
                    f"Auto-refresh: {len(labels)} feed(s) due — "
                    + ", ".join(labels)
                ),
            }))

    # ══════════════════════════════════════════════════════════════════════════
    #  run_repl override — starts background task alongside the REPL loop
    # ══════════════════════════════════════════════════════════════════════════

    def run_repl(self):
        try:
            if not inspect.iscoroutinefunction(self.process_command):
                raise TypeError("self.process_command must be an async function")
            print(f"Launching App: {self.app_name}", flush=True)

            async def _main():
                # Launch the auto-refresh watcher as a background task.
                self._bg_task = asyncio.create_task(self._auto_refresh_loop())
                try:
                    await self._loop()          # existing REPL stdin loop
                finally:
                    self._bg_task.cancel()
                    try:
                        await self._bg_task
                    except asyncio.CancelledError:
                        pass
                    print("[RSS] auto-refresh task stopped.", flush=True)

            asyncio.run(_main())
        except Exception as e:
            sys.stdout.write(f"[#APP_ERROR>{str(e)}]")

    # ══════════════════════════════════════════════════════════════════════════
    #  Commands
    # ══════════════════════════════════════════════════════════════════════════

    # ── subscribe ──────────────────────────────────────────────────────────────

    async def _cmd_subscribe(self, se_interface, episode_id, pos, kw):
        if len(pos) < 2:
            return se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "Usage: subscribe <url> <label> [refresh=<minutes>]",
            }))

        url, label = pos[0], pos[1]
        refresh    = max(1, int(kw.get("refresh", 60)))

        if not url.startswith(("http://", "https://")):
            return se_interface.send_message(json.dumps({
                "status":  "error",
                "message": f"URL must start with http:// or https://. Got: {url}",
            }))

        with _db_lock:
            conn = _get_conn()
            try:
                conn.execute("""
                    INSERT INTO subscriptions
                        (episode_id, label, url, refresh_minutes, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, label) DO UPDATE SET
                        url             = excluded.url,
                        refresh_minutes = excluded.refresh_minutes
                """, (episode_id, label, url, refresh, time.time()))
                conn.commit()
            finally:
                conn.close()

        print(f"[RSS] ✓ subscribe episode={episode_id} label={label}", flush=True)
        se_interface.send_message(json.dumps({
            "status":          "ok",
            "action":          "subscribe",
            "label":           label,
            "url":             url,
            "refresh_minutes": refresh,
            "message":         (
                f"Subscribed to '{label}'. Refresh every {refresh} min. "
                f"Run 'fetch {label}' to load items now. "
                f"Auto-refresh will trigger when the window elapses."
            ),
        }))

    # ── unsubscribe ────────────────────────────────────────────────────────────

    async def _cmd_unsubscribe(self, se_interface, episode_id, pos, kw):
        if not pos:
            return se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "Usage: unsubscribe <label>",
            }))

        label = pos[0]
        with _db_lock:
            conn = _get_conn()
            try:
                cur = conn.execute(
                    "DELETE FROM subscriptions WHERE episode_id=? AND label=?",
                    (episode_id, label),
                )
                conn.execute(
                    "DELETE FROM items WHERE episode_id=? AND feed_label=?",
                    (episode_id, label),
                )
                conn.commit()
                deleted = cur.rowcount
            finally:
                conn.close()

        if deleted:
            se_interface.send_message(json.dumps({
                "status":  "ok",
                "action":  "unsubscribe",
                "label":   label,
                "message": f"Unsubscribed from '{label}' and cleared its item cache.",
            }))
        else:
            se_interface.send_message(json.dumps({
                "status":  "error",
                "message": f"No subscription found with label '{label}'.",
            }))

    # ── list ───────────────────────────────────────────────────────────────────

    async def _cmd_list(self, se_interface, episode_id, pos, kw):
        with _db_lock:
            conn = _get_conn()
            try:
                rows = conn.execute("""
                    SELECT s.label, s.url, s.refresh_minutes, s.last_fetched_at,
                           COUNT(i.id)                                       AS total_items,
                           COALESCE(SUM(CASE WHEN i.seen=0 THEN 1 END), 0)  AS unseen_items
                    FROM subscriptions s
                    LEFT JOIN items i
                           ON i.episode_id=s.episode_id AND i.feed_label=s.label
                    WHERE s.episode_id=?
                    GROUP BY s.label
                    ORDER BY s.created_at
                """, (episode_id,)).fetchall()
            finally:
                conn.close()

        if not rows:
            return se_interface.send_message(json.dumps({
                "status":        "ok",
                "action":        "list",
                "subscriptions": [],
                "message":       "No subscriptions yet. Use: subscribe <url> <label>",
            }))

        se_interface.send_message(json.dumps({
            "status": "ok",
            "action": "list",
            "count":  len(rows),
            "subscriptions": [
                {
                    "label":           r["label"],
                    "url":             r["url"],
                    "refresh_minutes": r["refresh_minutes"],
                    "last_fetched":    _fmt_ts(r["last_fetched_at"]),
                    "total_items":     r["total_items"] or 0,
                    "unseen_items":    r["unseen_items"],
                }
                for r in rows
            ],
        }))

    # ── check (respects refresh rate) ─────────────────────────────────────────

    async def _cmd_check(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None
        await self._do_fetch(se_interface, episode_id, label=label, force=False)

    # ── fetch (force, ignore refresh rate) ────────────────────────────────────

    async def _cmd_fetch(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None
        await self._do_fetch(se_interface, episode_id, label=label, force=True)

    # ── poll (check all subs) ─────────────────────────────────────────────────

    async def _cmd_poll(self, se_interface, episode_id, pos, kw):
        await self._do_fetch(se_interface, episode_id, label=None, force=False, all_feeds=True)

    # ── peek (unseen items, no side-effects) ───────────────────────────────────

    async def _cmd_peek(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None
        n     = int(kw.get("n", 20))

        with _db_lock:
            conn = _get_conn()
            try:
                if label:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label
                        FROM items
                        WHERE episode_id=? AND feed_label=? AND seen=0
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, label, n)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label
                        FROM items
                        WHERE episode_id=? AND seen=0
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, n)).fetchall()
            finally:
                conn.close()

        se_interface.send_message(json.dumps({
            "status": "ok",
            "action": "peek",
            "count":  len(rows),
            "note":   "Items not marked as seen. Use 'check' to fetch+mark.",
            "items": [
                {
                    "feed":     r["feed_label"],
                    "title":    r["title"],
                    "link":     r["link"],
                    "summary":  (r["summary"] or "")[:300],
                    "pub_date": r["pub_date"],
                }
                for r in rows
            ],
        }))

    # ── items (all cached, incl seen) ─────────────────────────────────────────

    async def _cmd_items(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None
        n     = int(kw.get("n", 15))

        with _db_lock:
            conn = _get_conn()
            try:
                if label:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label, seen
                        FROM items
                        WHERE episode_id=? AND feed_label=?
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, label, n)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label, seen
                        FROM items
                        WHERE episode_id=?
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, n)).fetchall()
            finally:
                conn.close()

        se_interface.send_message(json.dumps({
            "status": "ok",
            "action": "items",
            "count":  len(rows),
            "items": [
                {
                    "feed":     r["feed_label"],
                    "title":    r["title"],
                    "link":     r["link"],
                    "summary":  (r["summary"] or "")[:300],
                    "pub_date": r["pub_date"],
                    "seen":     bool(r["seen"]),
                }
                for r in rows
            ],
        }))

    # ── search ─────────────────────────────────────────────────────────────────

    async def _cmd_search(self, se_interface, episode_id, pos, kw):
        if not pos:
            return se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "Usage: search <query> [in=<label>] [n=<count>]",
            }))

        query  = " ".join(pos)
        label  = kw.get("in")
        n      = int(kw.get("n", 10))

        with _db_lock:
            conn = _get_conn()
            try:
                if label:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label
                        FROM items WHERE episode_id=? AND feed_label=?
                        ORDER BY cached_at DESC LIMIT 500
                    """, (episode_id, label)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT title, link, summary, pub_date, feed_label
                        FROM items WHERE episode_id=?
                        ORDER BY cached_at DESC LIMIT 500
                    """, (episode_id,)).fetchall()
            finally:
                conn.close()

        if not rows:
            return se_interface.send_message(json.dumps({
                "status":  "ok",
                "action":  "search",
                "query":   query,
                "results": [],
                "message": "No items cached yet. Run 'check' or 'fetch' first.",
            }))

        corpus = [(r["title"] or "") + " " + (r["summary"] or "") for r in rows]

        if BM25_OK:
            tokenized = [doc.lower().split() for doc in corpus]
            bm25      = BM25Okapi(tokenized)
            scores    = bm25.get_scores(query.lower().split())
            ranked    = sorted(zip(scores, rows), key=lambda x: -x[0])
            hits      = [r for score, r in ranked if score > 0.0][:n]
        else:
            ql   = query.lower()
            hits = [
                r for r in rows
                if ql in (r["title"]   or "").lower()
                or ql in (r["summary"] or "").lower()
            ][:n]

        se_interface.send_message(json.dumps({
            "status":  "ok",
            "action":  "search",
            "query":   query,
            "engine":  "bm25" if BM25_OK else "substring",
            "count":   len(hits),
            "results": [
                {
                    "feed":     r["feed_label"],
                    "title":    r["title"],
                    "link":     r["link"],
                    "summary":  (r["summary"] or "")[:300],
                    "pub_date": r["pub_date"],
                }
                for r in hits
            ],
        }))

    # ── digest (compact title+link list for briefings) ─────────────────────────

    async def _cmd_digest(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None
        n     = int(kw.get("n", 10))

        with _db_lock:
            conn = _get_conn()
            try:
                if label:
                    rows = conn.execute("""
                        SELECT title, link, pub_date, feed_label
                        FROM items
                        WHERE episode_id=? AND feed_label=? AND seen=0
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, label, n)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT title, link, pub_date, feed_label
                        FROM items
                        WHERE episode_id=? AND seen=0
                        ORDER BY cached_at DESC LIMIT ?
                    """, (episode_id, n)).fetchall()
            finally:
                conn.close()

        if not rows:
            return se_interface.send_message(json.dumps({
                "status":  "ok",
                "action":  "digest",
                "count":   0,
                "digest":  [],
                "message": "No unseen items. Run 'check' to fetch new items.",
            }))

        with _db_lock:
            conn = _get_conn()
            try:
                for r in rows:
                    conn.execute("""
                        UPDATE items SET seen=1
                        WHERE episode_id=? AND feed_label=? AND title=?
                    """, (episode_id, r["feed_label"], r["title"]))
                conn.commit()
            finally:
                conn.close()

        se_interface.send_message(json.dumps({
            "status": "ok",
            "action": "digest",
            "count":  len(rows),
            "note":   "Items marked as seen.",
            "digest": [
                {
                    "feed":     r["feed_label"],
                    "title":    r["title"],
                    "link":     r["link"],
                    "pub_date": r["pub_date"],
                }
                for r in rows
            ],
        }))

    # ── clear_seen ─────────────────────────────────────────────────────────────

    async def _cmd_clear_seen(self, se_interface, episode_id, pos, kw):
        label = pos[0] if pos else None

        with _db_lock:
            conn = _get_conn()
            try:
                if label:
                    conn.execute(
                        "UPDATE items SET seen=0 WHERE episode_id=? AND feed_label=?",
                        (episode_id, label),
                    )
                else:
                    conn.execute(
                        "UPDATE items SET seen=0 WHERE episode_id=?",
                        (episode_id,),
                    )
                conn.commit()
                count = conn.execute("SELECT changes()").fetchone()[0]
            finally:
                conn.close()

        scope = f"'{label}'" if label else "all subscriptions"
        se_interface.send_message(json.dumps({
            "status":  "ok",
            "action":  "clear_seen",
            "message": (
                f"Reset seen flag for {count} item(s) in {scope}. "
                f"Next 'check' will re-report them."
            ),
        }))

    # ── status ─────────────────────────────────────────────────────────────────

    async def _cmd_status(self, se_interface, episode_id, pos, kw):
        now = time.time()
        with _db_lock:
            conn = _get_conn()
            try:
                rows = conn.execute("""
                    SELECT s.label, s.url, s.refresh_minutes, s.last_fetched_at,
                           COALESCE(COUNT(i.id), 0)                              AS total,
                           COALESCE(SUM(CASE WHEN i.seen=0 THEN 1 END), 0)       AS unseen
                    FROM subscriptions s
                    LEFT JOIN items i
                           ON i.episode_id=s.episode_id AND i.feed_label=s.label
                    WHERE s.episode_id=?
                    GROUP BY s.label
                    ORDER BY s.label
                """, (episode_id,)).fetchall()
            finally:
                conn.close()

        feeds = []
        for r in rows:
            lf        = r["last_fetched_at"] or 0
            elapsed   = now - lf if lf else None
            refresh_s = r["refresh_minutes"] * 60
            ready     = elapsed is None or elapsed >= refresh_s
            next_in   = max(0, int((refresh_s - elapsed) / 60)) if elapsed and not ready else 0

            feeds.append({
                "label":             r["label"],
                "url":               r["url"],
                "refresh_minutes":   r["refresh_minutes"],
                "last_fetched":      _fmt_ts(lf if lf else None),
                "ready_to_poll":     ready,
                "next_check_in_min": next_in,
                "total_items":       r["total"],
                "unseen_items":      r["unseen"],
            })

        se_interface.send_message(json.dumps({
            "status":             "ok",
            "action":             "status",
            "episode_id":         episode_id,
            "subscription_count": len(feeds),
            "auto_refresh_interval_s": _AUTO_REFRESH_INTERVAL_S,
            "feeds":              feeds,
        }))

    # ── help ───────────────────────────────────────────────────────────────────

    async def _cmd_help(self, se_interface, episode_id, pos, kw):
        se_interface.send_message(json.dumps({
            "status": "ok",
            "action": "help",
            "auto_refresh": (
                f"Background task fires every {_AUTO_REFRESH_INTERVAL_S}s. "
                "When a feed's refresh window elapses, send_and_invoke is called "
                "automatically — no manual 'poll' needed."
            ),
            "commands": {
                "subscribe <url> <label> [refresh=<min>]": "Subscribe to an RSS/Atom feed",
                "unsubscribe <label>":                     "Remove subscription + clear cache",
                "list":                                    "List subscriptions for this episode",
                "check [<label>]":                         "Fetch new items (respects refresh rate)",
                "fetch [<label>]":                         "Force-fetch ignoring refresh rate",
                "poll":                                    "Check ALL subscriptions for new items",
                "peek [<label>] [n=<N>]":                  "View unseen items without marking seen",
                "items [<label>] [n=<N>]":                 "Recent cached items (all, incl. seen)",
                "search <query> [in=<label>] [n=<N>]":    "BM25 / substring search cached items",
                "digest [<label>] [n=<N>]":               "Compact title+link digest; marks seen",
                "clear_seen [<label>]":                    "Reset seen flags for re-reporting",
                "status":                                  "Timing, counts, ready-to-poll flags",
                "help":                                    "This command list",
            },
        }))

    # ══════════════════════════════════════════════════════════════════════════
    #  Core fetch logic (shared by check / fetch / poll / auto-refresh)
    # ══════════════════════════════════════════════════════════════════════════

    async def _do_fetch(
        self,
        se_interface,
        episode_id: str,
        label:      str | None,
        force:      bool,
        all_feeds:  bool = False,
    ) -> None:
        if not FEEDPARSER_OK:
            return se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "feedparser not installed. Run: pip install feedparser",
            }))

        # ── resolve which subs to process ─────────────────────────────────────
        with _db_lock:
            conn = _get_conn()
            try:
                if all_feeds or label is None:
                    subs = conn.execute(
                        "SELECT * FROM subscriptions WHERE episode_id=?",
                        (episode_id,),
                    ).fetchall()
                else:
                    subs = conn.execute(
                        "SELECT * FROM subscriptions WHERE episode_id=? AND label=?",
                        (episode_id, label),
                    ).fetchall()
            finally:
                conn.close()

        if not subs:
            msg = (
                "No subscriptions found."
                if (all_feeds or label is None)
                else f"No subscription with label '{label}'."
            )
            return se_interface.send_message(json.dumps({"status": "error", "message": msg}))

        now     = time.time()
        results = []

        for sub in subs:
            sub_label = sub["label"]
            sub_url   = sub["url"]
            refresh_s = sub["refresh_minutes"] * 60
            last_f    = sub["last_fetched_at"] or 0
            elapsed   = now - last_f

            # ── skip if recently fetched and not forced ────────────────────────
            if not force and elapsed < refresh_s:
                remaining_min = int((refresh_s - elapsed) / 60)
                results.append({
                    "label":          sub_label,
                    "status":         "skipped",
                    "reason":         (
                        f"Fetched {int(elapsed/60)} min ago. "
                        f"Next in {remaining_min} min."
                    ),
                    "new_item_count": 0,
                    "new_items":      [],
                })
                continue

            # ── fetch feed (with timeout) ──────────────────────────────────────
            loop = asyncio.get_running_loop()
            try:
                feed = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda u=sub_url: feedparser.parse(u)),
                    timeout=_FETCH_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                results.append({
                    "label":          sub_label,
                    "status":         "error",
                    "reason":         f"Timed out after {_FETCH_TIMEOUT_S}s",
                    "new_item_count": 0,
                    "new_items":      [],
                })
                continue
            except Exception as exc:
                results.append({
                    "label":          sub_label,
                    "status":         "error",
                    "reason":         str(exc),
                    "new_item_count": 0,
                    "new_items":      [],
                })
                continue

            if feed.bozo and not feed.entries:
                results.append({
                    "label":          sub_label,
                    "status":         "error",
                    "reason":         (
                        f"Feed parse error: "
                        f"{getattr(feed, 'bozo_exception', 'malformed feed')}"
                    ),
                    "new_item_count": 0,
                    "new_items":      [],
                })
                continue

            # ── dedup: what GUIDs are already stored? ─────────────────────────
            with _db_lock:
                conn = _get_conn()
                try:
                    existing_guids = {
                        r[0] for r in conn.execute(
                            "SELECT guid FROM items WHERE episode_id=? AND feed_label=?",
                            (episode_id, sub_label),
                        ).fetchall()
                    }
                finally:
                    conn.close()

            # ── parse entries ─────────────────────────────────────────────────
            new_items: list[dict] = []
            for entry in feed.entries:
                guid = (
                    getattr(entry, "id",    None)
                    or getattr(entry, "link",  None)
                    or getattr(entry, "title", None)
                    or ""
                )
                if not guid or guid in existing_guids:
                    continue

                title   = _strip_html(getattr(entry, "title",   ""))
                link    = getattr(entry, "link",    "")
                summary = _strip_html(
                    getattr(entry, "summary",      "")
                    or getattr(entry, "description", "")
                )[:800]

                pub_date = (
                    getattr(entry, "published", "")
                    or getattr(entry, "updated",   "")
                )

                new_items.append({
                    "guid":     guid,
                    "title":    title,
                    "link":     link,
                    "summary":  summary,
                    "pub_date": pub_date,
                })

            # ── persist new items ─────────────────────────────────────────────
            with _db_lock:
                conn = _get_conn()
                try:
                    if new_items:
                        conn.executemany("""
                            INSERT OR IGNORE INTO items
                                (episode_id, feed_label, feed_url,
                                 guid, title, link, summary, pub_date,
                                 cached_at, seen)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """, [
                            (episode_id, sub_label, sub_url,
                             i["guid"], i["title"], i["link"],
                             i["summary"], i["pub_date"], now)
                            for i in new_items
                        ])
                    conn.execute(
                        "UPDATE subscriptions SET last_fetched_at=? "
                        "WHERE episode_id=? AND label=?",
                        (now, episode_id, sub_label),
                    )
                    conn.commit()
                finally:
                    conn.close()

            # mark new items as seen immediately (they've been returned to agent)
            if new_items:
                with _db_lock:
                    conn = _get_conn()
                    try:
                        conn.executemany(
                            "UPDATE items SET seen=1 "
                            "WHERE episode_id=? AND feed_label=? AND guid=?",
                            [(episode_id, sub_label, i["guid"]) for i in new_items],
                        )
                        conn.commit()
                    finally:
                        conn.close()

            results.append({
                "label":          sub_label,
                "status":         "ok",
                "new_item_count": len(new_items),
                "new_items": [
                    {
                        "title":    i["title"],
                        "link":     i["link"],
                        "summary":  i["summary"][:300],
                        "pub_date": i["pub_date"],
                    }
                    for i in new_items
                ],
            })

        total_new = sum(r.get("new_item_count", 0) for r in results)
        se_interface.send_message(json.dumps({
            "status":          "ok",
            "action":          "fetch",
            "total_new_items": total_new,
            "feed_count":      len(results),
            "feeds":           results,
            "message":         f"Found {total_new} new item(s) across {len(results)} feed(s).",
        }))


# ── entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RSSApp().run_repl()