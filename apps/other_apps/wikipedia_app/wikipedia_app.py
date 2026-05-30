# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Rajaganapathy M
# For commercial licensing: https://github.com/RajaGanapathyM/kattalai

import json
import re
import sys
from pathlib import Path
from datetime import datetime

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Optional heavy deps loaded lazily ─────────────────────────────────────────

def _wiki():
    try:
        import wikipedia
        return wikipedia
    except ImportError:
        raise ImportError(
            "wikipedia is required: pip install wikipedia-api"
            "\nNote: use 'wikipedia' package, not 'wikipedia-api'"
        )

def _requests():
    try:
        import requests
        return requests
    except ImportError:
        raise ImportError("requests is required: pip install requests")


# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_LANG      = "en"
DEFAULT_RESULTS   = 5
MAX_SUMMARY_CHARS = 2000
WIKIPEDIA_API_URL = "https://{lang}.wikipedia.org/w/api.php"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


WIKI_USER_AGENT = (
    "KattalaiWikipediaApp/1.0 "
    "(https://github.com/RajaGanapathyM/kattalai; kattalai-agent-runtime)"
)


def _wiki_api(lang: str, params: dict) -> dict:
    """Raw MediaWiki API call. Returns parsed JSON.
    
    Wikipedia requires a descriptive User-Agent per:
    https://www.mediawiki.org/wiki/API:Etiquette
    """
    requests = _requests()
    url = WIKIPEDIA_API_URL.format(lang=lang)
    params.setdefault("format", "json")
    params.setdefault("utf8", 1)
    headers = {"User-Agent": WIKI_USER_AGENT}
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _strip_html(text: str) -> str:
    """Very light HTML tag remover for snippet fields."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


# ── App class ──────────────────────────────────────────────────────────────────

class WikipediaApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="Wikipedia App", app_icon="📖")

    # ── Response builders ──────────────────────────────────────────────────────

    def _ok(self, command: str, **extra) -> dict:
        return {"status": "success", "command": command, **extra}

    def _err(self, command: str, code: str, reason: str) -> dict:
        return {"status": "error", "command": command, "error_code": code, "reason": reason}

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
                "Valid: search, summary, sections, content, links, images, geo, random, langlinks"
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
    # Commands
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_search(self, _si, kv: dict) -> dict:
        """Full-text search: returns a list of matching article titles + snippets."""
        query = kv.get("query") or " ".join(kv.get("_bare", []))
        if not query:
            return self._err("search", "missing_argument", "Missing 'query' argument.")

        lang    = kv.get("lang", DEFAULT_LANG)
        limit   = int(kv.get("limit", DEFAULT_RESULTS))

        data = _wiki_api(lang, {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srprop": "snippet|titlesnippet|wordcount|timestamp",
        })

        raw_results = data.get("query", {}).get("search", [])
        results = [
            {
                "title":      r["title"],
                "pageid":     r["pageid"],
                "snippet":    _strip_html(r.get("snippet", "")),
                "word_count": r.get("wordcount", 0),
                "timestamp":  r.get("timestamp", ""),
            }
            for r in raw_results
        ]

        return self._ok(
            "search",
            query=query,
            lang=lang,
            total_hits=data.get("query", {}).get("searchinfo", {}).get("totalhits", len(results)),
            results=results,
        )

    async def _cmd_summary(self, _si, kv: dict) -> dict:
        """Fetch the introductory summary of a Wikipedia article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("summary", "missing_argument", "Missing 'title' argument.")

        lang    = kv.get("lang", DEFAULT_LANG)
        max_chars = int(kv.get("max_chars", MAX_SUMMARY_CHARS))

        data = _wiki_api(lang, {
            "action": "query",
            "titles": title,
            "prop": "extracts|info",
            "exintro": True,
            "explaintext": True,
            "inprop": "url",
            "redirects": 1,
        })

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("summary", "page_not_found", f"No Wikipedia article found for '{title}'.")

        extract = page.get("extract", "")
        if max_chars and len(extract) > max_chars:
            extract = extract[:max_chars].rsplit(" ", 1)[0] + "…"

        return self._ok(
            "summary",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            lang=lang,
            url=page.get("fullurl", f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"),
            summary=extract,
            char_count=len(extract),
        )

    async def _cmd_sections(self, _si, kv: dict) -> dict:
        """List all section headings of a Wikipedia article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("sections", "missing_argument", "Missing 'title' argument.")

        lang = kv.get("lang", DEFAULT_LANG)

        data = _wiki_api(lang, {
            "action": "parse",
            "page": title,
            "prop": "sections",
            "redirects": 1,
        })

        if "error" in data:
            return self._err("sections", "api_error", data["error"].get("info", str(data["error"])))

        raw_sections = data.get("parse", {}).get("sections", [])
        sections = [
            {
                "index":  s.get("index"),
                "level":  int(s.get("level", 1)),
                "anchor": s.get("anchor", ""),
                "title":  s.get("line", ""),
            }
            for s in raw_sections
        ]

        return self._ok(
            "sections",
            title=data.get("parse", {}).get("title", title),
            pageid=data.get("parse", {}).get("pageid"),
            lang=lang,
            section_count=len(sections),
            sections=sections,
        )

    async def _cmd_content(self, _si, kv: dict) -> dict:
        """Fetch full plain-text content of an article (or a specific section)."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("content", "missing_argument", "Missing 'title' argument.")

        lang    = kv.get("lang", DEFAULT_LANG)
        section = kv.get("section")   # section index (0-based string) from `sections` command

        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts|info",
            "explaintext": True,
            "inprop": "url",
            "redirects": 1,
        }
        if section is not None:
            params["exsectionformat"] = "plain"
            # section 0 = intro; higher numbers match `sections` index output
            params["exsection"] = section

        data = _wiki_api(lang, params)
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("content", "page_not_found", f"No Wikipedia article found for '{title}'.")

        extract = page.get("extract", "")

        return self._ok(
            "content",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            lang=lang,
            url=page.get("fullurl", f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"),
            section=section,
            char_count=len(extract),
            content=extract,
        )

    async def _cmd_links(self, _si, kv: dict) -> dict:
        """Return internal Wikipedia links present in an article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("links", "missing_argument", "Missing 'title' argument.")

        lang  = kv.get("lang", DEFAULT_LANG)
        limit = int(kv.get("limit", 50))

        data = _wiki_api(lang, {
            "action": "query",
            "titles": title,
            "prop": "links",
            "pllimit": min(limit, 500),
            "redirects": 1,
        })

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("links", "page_not_found", f"No Wikipedia article found for '{title}'.")

        raw_links = page.get("links", [])
        links = [lk["title"] for lk in raw_links if lk.get("ns", 0) == 0]

        return self._ok(
            "links",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            lang=lang,
            link_count=len(links),
            links=links,
        )

    async def _cmd_images(self, _si, kv: dict) -> dict:
        """List image filenames used in a Wikipedia article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("images", "missing_argument", "Missing 'title' argument.")

        lang  = kv.get("lang", DEFAULT_LANG)
        limit = int(kv.get("limit", 20))

        data = _wiki_api(lang, {
            "action": "query",
            "titles": title,
            "prop": "images",
            "imlimit": min(limit, 500),
            "redirects": 1,
        })

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("images", "page_not_found", f"No Wikipedia article found for '{title}'.")

        raw_images = page.get("images", [])
        images = [img["title"] for img in raw_images]

        return self._ok(
            "images",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            lang=lang,
            image_count=len(images),
            images=images,
        )

    async def _cmd_geo(self, _si, kv: dict) -> dict:
        """Return geographic coordinates of a place article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("geo", "missing_argument", "Missing 'title' argument.")

        lang = kv.get("lang", DEFAULT_LANG)

        data = _wiki_api(lang, {
            "action": "query",
            "titles": title,
            "prop": "coordinates",
            "redirects": 1,
        })

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("geo", "page_not_found", f"No Wikipedia article found for '{title}'.")

        coords = page.get("coordinates", [])
        if not coords:
            return self._err(
                "geo", "no_coordinates",
                f"Article '{page.get('title', title)}' has no geographic coordinates."
            )

        c = coords[0]
        return self._ok(
            "geo",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            lang=lang,
            lat=c.get("lat"),
            lon=c.get("lon"),
            globe=c.get("globe", "earth"),
        )

    async def _cmd_random(self, _si, kv: dict) -> dict:
        """Return one or more random Wikipedia article titles."""
        lang  = kv.get("lang", DEFAULT_LANG)
        count = int(kv.get("count", 1))

        data = _wiki_api(lang, {
            "action": "query",
            "list": "random",
            "rnnamespace": 0,
            "rnlimit": min(count, 10),
        })

        pages = data.get("query", {}).get("random", [])
        articles = [{"title": p["title"], "pageid": p["id"]} for p in pages]

        return self._ok("random", lang=lang, count=len(articles), articles=articles)

    async def _cmd_langlinks(self, _si, kv: dict) -> dict:
        """List available language versions of an article."""
        title = kv.get("title") or " ".join(kv.get("_bare", []))
        if not title:
            return self._err("langlinks", "missing_argument", "Missing 'title' argument.")

        lang  = kv.get("lang", DEFAULT_LANG)
        limit = int(kv.get("limit", 30))

        data = _wiki_api(lang, {
            "action": "query",
            "titles": title,
            "prop": "langlinks",
            "lllimit": min(limit, 500),
            "redirects": 1,
        })

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if page.get("missing") is not None:
            return self._err("langlinks", "page_not_found", f"No Wikipedia article found for '{title}'.")

        raw = page.get("langlinks", [])
        langlinks = [{"lang": ll["lang"], "title": ll["*"]} for ll in raw]

        return self._ok(
            "langlinks",
            title=page.get("title", title),
            pageid=page.get("pageid"),
            source_lang=lang,
            available_languages=len(langlinks),
            langlinks=langlinks,
        )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = WikipediaApp()
    app.run_one_shot()