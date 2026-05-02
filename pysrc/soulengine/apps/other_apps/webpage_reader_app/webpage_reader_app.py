
# ── Headless toggle ────────────────────────────────────────────────────────────
HEADLESS: bool = False
PAGE_LOAD_WAIT_TIME: int = 10_000

# ── Write-class commands that require user permission ──────────────────────────
WRITE_COMMANDS: set = {"save"}

# ── Dialog messages ────────────────────────────────────────────────────────────
DIALOG_MESSAGES = {
    "save": "Allow Webpage Reader to fetch this URL and write the content to disk?",
}

# ──────────────────────────────────────────────────────────────────────────────

import json
import re
import sys
import asyncio
import os
import logging
from pathlib import Path
from urllib.parse import urlparse, urljoin

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
logging.getLogger("playwright").setLevel(logging.ERROR)

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
from se_app_utils.soulengine import soul_engine_app


# ── GUI helpers ────────────────────────────────────────────────────────────────

def _show_tkinter_error(title: str, message: str) -> None:
    """Show a modal error dialog (startup dependency checks only).
    Falls back to stderr if tkinter unavailable."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except Exception:
        print(f"[ERROR] {title}: {message}", file=sys.stderr)


# ── Playwright / Chromium availability ────────────────────────────────────────

try:
    from playwright.async_api import async_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


def _is_chromium_installed() -> bool:
    if not _HAS_PLAYWRIGHT:
        return False
    try:
        search_bases: list = []
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            search_bases.append(Path(local_app) / "ms-playwright")
        search_bases.append(Path.home() / ".cache" / "ms-playwright")
        env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        if env_path:
            search_bases.append(Path(env_path))

        for base in search_bases:
            if not base.exists():
                continue
            for d in base.glob("chromium-*"):
                for exe_name in ("chrome.exe", "chrome", "chromium"):
                    if any(d.rglob(exe_name)):
                        return True
        return False
    except Exception:
        return False


_HAS_CHROMIUM: bool = False
if _HAS_PLAYWRIGHT:
    _HAS_CHROMIUM = _is_chromium_installed()
    if not _HAS_CHROMIUM:
        _show_tkinter_error(
            "Playwright Chromium Not Found — Webpage Reader",
            "The Chromium browser required by Playwright is not installed.\n\n"
            "To install it, run:\n\n"
            "    playwright install chromium\n\n"
            "The Webpage Reader app will not function until Chromium is available.",
        )
else:
    _show_tkinter_error(
        "Playwright Not Installed — Webpage Reader",
        "The 'playwright' Python package is not installed.\n\n"
        "To install it, run:\n\n"
        "    pip install playwright\n"
        "    playwright install chromium\n\n"
        "The Webpage Reader app will not function until Playwright is available.",
    )


# ── Optional deps ──────────────────────────────────────────────────────────────

try:
    import html2text
    _HAS_HTML2TEXT = True
except ImportError:
    _HAS_HTML2TEXT = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False


# ──────────────────────────────────────────────────────────────────────────────

class WebpageReaderApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="Webpage Reader", app_icon="🌐")

        self._base_dir  = Path(__file__).parent
        self._saved_dir = self._base_dir / "webpage_reader_saves"

        self._playwright = None
        self._browser    = None
        self._current_url: str = ""

    # ──────────────────────────────────────────────────── browser lifecycle ───

    async def _get_browser(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        await self._close_browser()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return self._browser

    async def _close_browser(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ────────────────────────────────────────────────────────── page fetch ───

    async def _fetch_page(self, url: str) -> dict:
        browser = await self._get_browser()
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        page = await context.new_page()

        async def _route_handler(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _route_handler)

        result: dict
        try:
            response = None
            try:
                response = await page.goto(url, wait_until="networkidle",
                                           timeout=PAGE_LOAD_WAIT_TIME)
            except Exception:
                pass
            final_url         = page.url
            title             = await page.title()
            html              = await page.content()
            status            = response.status if response else 0
            self._current_url = final_url
            result = {"status": status, "url": final_url, "title": title, "html": html}
        except Exception as exc:
            result = {"status": "error", "message": str(exc), "url": url}
        finally:
            await context.close()
        return result

    # ────────────────────────────────────────────────── content processing ───

    def _html_to_markdown(self, html: str, base_url: str = "") -> str:
        if not _HAS_HTML2TEXT:
            return re.sub(r"<[^>]+>", " ", html).strip()
        h = html2text.HTML2Text()
        h.ignore_links        = True
        h.ignore_images       = True
        h.ignore_emphasis     = False
        h.body_width          = 0
        h.skip_internal_links = True
        h.baseurl             = base_url
        return h.handle(html)

    def _prune_markdown(self, md: str, min_words: int = 10) -> str:
        paragraphs = re.split(r"\n{2,}", md)
        return "\n\n".join(p for p in paragraphs if len(p.split()) >= min_words)

    def _bm25_filter(self, md: str, query: str, top_k_ratio: float = 0.4) -> str:
        if not _HAS_BM25 or not query.strip():
            return md
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", md) if p.strip()]
        if not paragraphs:
            return md
        bm25   = BM25Okapi([p.lower().split() for p in paragraphs])
        scores = bm25.get_scores(query.lower().split())
        top_k  = max(1, int(len(paragraphs) * top_k_ratio))
        ranked = sorted(enumerate(paragraphs), key=lambda x: scores[x[0]], reverse=True)[:top_k]
        ranked.sort(key=lambda x: x[0])
        return "\n\n".join(p for _, p in ranked)

    async def _read_pipeline(self, url: str, query: str = "") -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        if not _HAS_HTML2TEXT:
            return {"status": "error",
                    "message": "html2text not installed. Run: pip install html2text"}

        page = await self._fetch_page(url)

        if page.get("status") == "error":
            return page
        http_status = page.get("status", 0)
        if isinstance(http_status, int) and http_status >= 400:
            return {
                "status":  "error",
                "message": f"HTTP {http_status} received for {page.get('url', url)}",
                "url":     page.get("url", url),
            }

        md = self._html_to_markdown(page["html"], base_url=page["url"])
        md = self._prune_markdown(md)
        if query:
            md = self._bm25_filter(md, query)
        return {
            "status":     "ok",
            "url":        page["url"],
            "title":      page["title"],
            "char_count": len(md),
            "markdown":   md,
        }

    # ─────────────────────────────────────────────────────────── helpers ───

    def _no_playwright(self) -> dict:
        if not _HAS_PLAYWRIGHT:
            return {"status": "error",
                    "message": "playwright not installed. "
                               "Run: pip install playwright && playwright install chromium"}
        return {"status": "error",
                "message": "Chromium browser not installed. Run: playwright install chromium"}

    def _sanitize_filename(self, url: str) -> str:
        parsed = urlparse(url)
        slug   = re.sub(r"[^\w\-]", "_", parsed.netloc + parsed.path)
        slug   = re.sub(r"_+", "_", slug).strip("_")
        return slug[:80] or "page"

    def _url_from_args(self, args: list):
        for i, a in enumerate(args):
            if a.startswith("http://") or a.startswith("https://"):
                return a, args[:i] + args[i + 1:]
        return "", list(args)

    # ─────────────────────────────────────────────────────── handlers ───
    # All handlers now receive (si, args) so write commands can call
    # si.request_permission without any extra plumbing.

    async def _handle_read(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        args = list(args)
        query = ""
        if "--query" in args:
            idx   = args.index("--query")
            query = " ".join(args[idx + 1:])
            args  = args[:idx]
        url, _ = self._url_from_args(args)
        if not url:
            return {"status": "error", "message": "Usage: read <url> [--query <text>]"}
        return await self._read_pipeline(url, query=query)

    async def _handle_save(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        args = list(args)
        query, out_path = "", None

        # Parse --out first (fixed-arity: flag + path)
        if "--out" in args:
            idx = args.index("--out")
            if idx + 1 < len(args):
                out_path = Path(args[idx + 1])
                args = args[:idx] + args[idx + 2:]

        # Parse --query (greedy: everything after the flag)
        if "--query" in args:
            idx   = args.index("--query")
            query = " ".join(args[idx + 1:])
            args  = args[:idx]

        url, _ = self._url_from_args(args)
        if not url:
            return {"status": "error",
                    "message": "Usage: save <url> [--out <path>] [--query <text>]"}

        self._saved_dir.mkdir(parents=True, exist_ok=True)
        dest_display = (
            str(out_path) if out_path
            else str(self._saved_dir / "<sanitized_url>.md")
        )

        if not si.request_permission(
            action="save",
            context={"url": url, "destination": dest_display},
            message=DIALOG_MESSAGES["save"],
        ):
            return {"status": "denied",
                    "message": "Save operation cancelled by user.",
                    "url": url}

        result = await self._read_pipeline(url, query=query)
        if result["status"] != "ok":
            return result

        if out_path is None:
            out_path = self._saved_dir / (self._sanitize_filename(result["url"]) + ".md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result["markdown"], encoding="utf-8")
        return {
            "status":     "saved",
            "url":        result["url"],
            "title":      result["title"],
            "file":       str(out_path),
            "char_count": result["char_count"],
        }

    async def _handle_raw(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        url, _ = self._url_from_args(list(args))
        if not url:
            return {"status": "error", "message": "Usage: raw <url>"}
        page = await self._fetch_page(url)
        if page.get("status") == "error":
            return page
        html = page.get("html", "")
        return {"status": "ok", "url": page["url"], "char_count": len(html), "html": html}

    async def _handle_meta(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        url, _ = self._url_from_args(list(args))
        if not url:
            return {"status": "error", "message": "Usage: meta <url>"}
        page = await self._fetch_page(url)
        if page.get("status") == "error":
            return page
        meta = {"title": page.get("title", "")}
        if _HAS_BS4:
            soup = BeautifulSoup(page["html"], "html.parser")
            for tag in soup.find_all("meta"):
                key   = tag.get("name") or tag.get("property") or ""
                value = tag.get("content", "")
                if key and value:
                    meta[key] = value
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                meta["canonical"] = canonical["href"]
        return {"status": "ok", "url": page["url"], "meta": meta}

    async def _handle_links(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        args = list(args)
        external_only = "--external-only" in args
        internal_only = "--internal-only" in args
        args = [a for a in args if a not in ("--external-only", "--internal-only")]
        url, _ = self._url_from_args(args)
        if not url:
            return {"status": "error",
                    "message": "Usage: links <url> [--internal-only | --external-only]"}
        page = await self._fetch_page(url)
        if page.get("status") == "error":
            return page
        base_parsed = urlparse(page["url"])
        internal: list = []
        external: list = []
        if _HAS_BS4:
            soup = BeautifulSoup(page["html"], "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                abs_href = urljoin(page["url"], href)
                entry    = {"href": abs_href, "text": a.get_text(strip=True)}
                (internal if urlparse(abs_href).netloc == base_parsed.netloc
                 else external).append(entry)
        else:
            for href in re.findall(r'href=["\']([^"\']+)["\']', page["html"]):
                href = href.strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                abs_href = urljoin(page["url"], href)
                entry    = {"href": abs_href, "text": ""}
                (internal if urlparse(abs_href).netloc == base_parsed.netloc
                 else external).append(entry)
        if external_only:
            links = external
        elif internal_only:
            links = internal
        else:
            links = internal + external
        return {
            "status":         "ok",
            "url":            page["url"],
            "internal_count": len(internal),
            "external_count": len(external),
            "links":          links,
        }

    async def _handle_images(self, si, args: list) -> dict:
        if not _HAS_PLAYWRIGHT or not _HAS_CHROMIUM:
            return self._no_playwright()
        url, _ = self._url_from_args(list(args))
        if not url:
            return {"status": "error", "message": "Usage: images <url>"}
        page = await self._fetch_page(url)
        if page.get("status") == "error":
            return page
        images: list = []
        if _HAS_BS4:
            soup = BeautifulSoup(page["html"], "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src", "").strip() or img.get("data-src", "").strip()
                if not src:
                    continue
                images.append({
                    "src":    urljoin(page["url"], src),
                    "alt":    img.get("alt", ""),
                    "width":  img.get("width", ""),
                    "height": img.get("height", ""),
                })
        else:
            for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', page["html"]):
                images.append({"src": urljoin(page["url"], src.strip()), "alt": ""})
        return {"status": "ok", "url": page["url"], "count": len(images), "images": images}

    # ─────────────────────────────────────────────────────── main entry ───

    async def process_command(self, se_interface, args):
        _commands = {
            "read":   self._handle_read,
            "save":   self._handle_save,
            "raw":    self._handle_raw,
            "meta":   self._handle_meta,
            "links":  self._handle_links,
            "images": self._handle_images,
        }

        if not args:
            result = {
                "status":  "error",
                "message": "No command or URL provided.",
                "usage": (
                    "read <url> [--query <text>] | "
                    "save <url> [--out <path>] [--query <text>] | "
                    "raw <url> | meta <url> | "
                    "links <url> [--internal-only | --external-only] | "
                    "images <url>"
                ),
            }
        else:
            cmd = args[0].lower()
            handler = _commands.get(cmd)
            if handler:
                result = await handler(se_interface, args[1:])
            else:
                # Bare URL → default LLM-friendly read
                result = await self._handle_read(se_interface, args)

        if isinstance(result, dict):
            result["current_url"] = self._current_url

        se_interface.send_message(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    app = WebpageReaderApp()
    app.run_repl()
