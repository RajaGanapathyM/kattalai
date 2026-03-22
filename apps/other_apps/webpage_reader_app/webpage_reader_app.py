import json
import re
import sys
import asyncio
import contextlib
import os
from pathlib import Path
from urllib.parse import urlparse, urljoin
import logging

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
logging.getLogger("playwright").setLevel(logging.ERROR)

from pathlib import Path
# .parent is 'myapp', .parent.parent is 'apps'
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Optional deps ──────────────────────────────────────────────────────────────

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

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

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE_DIR  = Path("G:\\bitBucketRepo\\bRowSe\\soul_engine\\src")
SAVED_DIR = BASE_DIR / "webpage_reader_saves"

# ── Shared browser instance ────────────────────────────────────────────────────

_PLAYWRIGHT  = None
_BROWSER: "Browser | None" = None


async def _get_browser() -> "Browser":
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is None or not _BROWSER.is_connected():
        _PLAYWRIGHT = await async_playwright().start()
        _BROWSER = await _PLAYWRIGHT.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
    return _BROWSER


async def _close_browser():
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER:
        await _BROWSER.close()
        _BROWSER = None
    if _PLAYWRIGHT:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None


# ── HTML → Markdown ────────────────────────────────────────────────────────────

def _html_to_markdown(html: str, base_url: str = "") -> str:
    """Convert HTML to clean markdown using html2text."""
    if not _HAS_HTML2TEXT:
        # Fallback: strip tags manually
        return re.sub(r"<[^>]+>", " ", html).strip()

    h = html2text.HTML2Text()
    h.ignore_links        = True
    h.ignore_images       = True
    h.ignore_emphasis     = False
    h.body_width          = 0       # no hard wraps
    h.skip_internal_links = True
    h.baseurl             = base_url
    return h.handle(html)


def _prune_markdown(md: str, min_words: int = 10) -> str:
    """
    Remove lines/paragraphs that are too short (nav fragments, single words, etc.)
    Mirrors crawl4ai's PruningContentFilter at a basic level.
    """
    paragraphs = re.split(r"\n{2,}", md)
    kept = []
    for para in paragraphs:
        words = para.split()
        if len(words) >= min_words:
            kept.append(para)
    return "\n\n".join(kept)


def _bm25_filter(md: str, query: str, top_k_ratio: float = 0.4) -> str:
    """
    Split markdown into paragraphs, score each against the query with BM25,
    and return the top fraction. Falls back to full text if rank_bm25 is absent.
    """
    if not _HAS_BM25 or not query.strip():
        return md

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", md) if p.strip()]
    if not paragraphs:
        return md

    tokenized_corpus = [p.lower().split() for p in paragraphs]
    bm25 = BM25Okapi(tokenized_corpus)
    query_tokens = query.lower().split()
    scores = bm25.get_scores(query_tokens)

    top_k = max(1, int(len(paragraphs) * top_k_ratio))
    ranked = sorted(
        enumerate(paragraphs),
        key=lambda x: scores[x[0]],
        reverse=True,
    )[:top_k]

    # Restore original paragraph order so reading flow is preserved
    ranked.sort(key=lambda x: x[0])
    return "\n\n".join(p for _, p in ranked)


# ── Core fetch ─────────────────────────────────────────────────────────────────

async def _fetch_page(url: str) -> dict:
    """
    Launch a Playwright page, wait for networkidle, and return raw data.
    Returns: {url, title, html, status}
    """
    browser = await _get_browser()
    context: BrowserContext = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        java_script_enabled=True,
        ignore_https_errors=True,
    )

    page = await context.new_page()

    # Block resource types that aren't needed for content extraction
    await page.route(
        "**/*",
        lambda route: asyncio.ensure_future(
            route.abort()
            if route.request.resource_type in ("image", "media", "font", "stylesheet")
            else route.continue_()
        ),
    )

    try:
        response = await page.goto(url, wait_until="networkidle", timeout=30_000)
        final_url = page.url
        title     = await page.title()
        html      = await page.content()
        status    = response.status if response else 0
    except Exception as exc:
        await context.close()
        return {"status": "error", "message": str(exc), "url": url}
    finally:
        await context.close()

    return {
        "status": status,
        "url":    final_url,
        "title":  title,
        "html":   html,
    }


# ── Public read pipeline ───────────────────────────────────────────────────────

async def read(url: str, query: str = "") -> dict:
    """
    Full LLM-friendly pipeline:
      Playwright fetch → html2text → prune → (optional BM25 filter)

    Returns result dict with 'markdown' key.
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()
    if not _HAS_HTML2TEXT:
        return {
            "status":  "error",
            "message": "html2text is not installed. Run: pip install html2text",
        }

    page = await _fetch_page(url)
    if page.get("status") == "error":
        return page

    md = _html_to_markdown(page["html"], base_url=page["url"])
    md = _prune_markdown(md)

    if query:
        md = _bm25_filter(md, query)

    return {
        "status":     "ok",
        "url":        page["url"],
        "title":      page["title"],
        "char_count": len(md),
        "markdown":   md,
    }


# ── Helper guards ──────────────────────────────────────────────────────────────

def _no_playwright() -> dict:
    return {
        "status":  "error",
        "message": (
            "playwright is not installed. Run: "
            "pip install playwright && playwright install chromium"
        ),
    }


def _sanitize_filename(url: str) -> str:
    parsed = urlparse(url)
    slug   = re.sub(r"[^\w\-]", "_", parsed.netloc + parsed.path)
    slug   = re.sub(r"_+", "_", slug).strip("_")
    return (slug[:80] or "page")


def _url_from_args(args: list[str]) -> tuple[str, list[str]]:
    for i, a in enumerate(args):
        if a.startswith("http://") or a.startswith("https://"):
            return a, args[:i] + args[i + 1:]
    return "", list(args)


# ── Command handlers ───────────────────────────────────────────────────────────

async def handle_read(args: list[str]) -> dict:
    """
    LLM-friendly read. Returns pruned markdown.
    Flag: --query <text>  →  BM25 filter pulls only query-relevant paragraphs.
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    query = ""
    if "--query" in args:
        idx   = args.index("--query")
        query = " ".join(args[idx + 1:])
        args  = args[:idx]

    url, _ = _url_from_args(args)
    print("READING URL:", url)
    if not url:
        return {"status": "error", "message": "Usage: read <url> [--query <text>]"}

    return await read(url, query=query)


async def handle_save(args: list[str]) -> dict:
    """
    Fetch → markdown → write to .md file.
    Flags: --out <filepath>  --query <text>
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    query = ""
    if "--query" in args:
        idx   = args.index("--query")
        query = " ".join(args[idx + 1:])
        args  = args[:idx]

    out_path = None
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out_path = Path(args[idx + 1])
            args     = args[:idx] + args[idx + 2:]

    url, _ = _url_from_args(args)
    if not url:
        return {"status": "error", "message": "Usage: save <url> [--out <path>] [--query <text>]"}

    result = await read(url, query=query)
    if result["status"] != "ok":
        return result

    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        out_path = SAVED_DIR / (_sanitize_filename(result["url"]) + ".md")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result["markdown"], encoding="utf-8")

    return {
        "status":     "saved",
        "url":        result["url"],
        "title":      result["title"],
        "file":       str(out_path),
        "char_count": result["char_count"],
    }


async def handle_raw(args: list[str]) -> dict:
    """Return the raw page HTML — useful for debugging or custom pipelines."""
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    url, _ = _url_from_args(args)
    if not url:
        return {"status": "error", "message": "Usage: raw <url>"}

    page = await _fetch_page(url)
    if page.get("status") == "error":
        return page

    html = page.get("html", "")
    return {
        "status":     "ok",
        "url":        page["url"],
        "char_count": len(html),
        "html":       html,
    }


async def handle_meta(args: list[str]) -> dict:
    """
    Extract page metadata: title, description, og:* tags, canonical URL, etc.
    Requires beautifulsoup4.
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    url, _ = _url_from_args(args)
    if not url:
        return {"status": "error", "message": "Usage: meta <url>"}

    page = await _fetch_page(url)
    if page.get("status") == "error":
        return page

    meta = {"title": page.get("title", "")}

    if _HAS_BS4:
        soup = BeautifulSoup(page["html"], "html.parser")

        # <meta name="..."> and <meta property="...">
        for tag in soup.find_all("meta"):
            key   = tag.get("name") or tag.get("property") or ""
            value = tag.get("content", "")
            if key and value:
                meta[key] = value

        # canonical
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            meta["canonical"] = canonical["href"]

    return {"status": "ok", "url": page["url"], "meta": meta}


async def handle_links(args: list[str]) -> dict:
    """
    Extract all hyperlinks from a page.
    Flags: --internal-only  --external-only
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    external_only = "--external-only" in args
    internal_only = "--internal-only" in args
    args = [a for a in args if a not in ("--external-only", "--internal-only")]

    url, _ = _url_from_args(args)
    if not url:
        return {
            "status":  "error",
            "message": "Usage: links <url> [--internal-only | --external-only]",
        }

    page = await _fetch_page(url)
    if page.get("status") == "error":
        return page

    base_parsed = urlparse(page["url"])
    internal, external = [], []

    if _HAS_BS4:
        soup = BeautifulSoup(page["html"], "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            abs_href = urljoin(page["url"], href)
            parsed   = urlparse(abs_href)
            entry    = {"href": abs_href, "text": a.get_text(strip=True)}
            if parsed.netloc == base_parsed.netloc:
                internal.append(entry)
            else:
                external.append(entry)
    else:
        # Regex fallback when bs4 is absent
        for href in re.findall(r'href=["\']([^"\']+)["\']', page["html"]):
            href = href.strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            abs_href = urljoin(page["url"], href)
            parsed   = urlparse(abs_href)
            entry    = {"href": abs_href, "text": ""}
            if parsed.netloc == base_parsed.netloc:
                internal.append(entry)
            else:
                external.append(entry)

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


async def handle_images(args: list[str]) -> dict:
    """
    Extract all images from a page (src, alt, width, height where available).
    """
    if not _HAS_PLAYWRIGHT:
        return _no_playwright()

    url, _ = _url_from_args(args)
    if not url:
        return {"status": "error", "message": "Usage: images <url>"}

    page = await _fetch_page(url)
    if page.get("status") == "error":
        return page

    images = []

    if _HAS_BS4:
        soup = BeautifulSoup(page["html"], "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "").strip()
            if not src:
                src = img.get("data-src", "").strip()
            if not src:
                continue
            abs_src = urljoin(page["url"], src)
            images.append({
                "src":    abs_src,
                "alt":    img.get("alt", ""),
                "width":  img.get("width", ""),
                "height": img.get("height", ""),
            })
    else:
        for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', page["html"]):
            images.append({"src": urljoin(page["url"], src.strip()), "alt": ""})

    return {
        "status": "ok",
        "url":    page["url"],
        "count":  len(images),
        "images": images,
    }


# ── Command router ─────────────────────────────────────────────────────────────

COMMANDS = {
    "read":   handle_read,
    "save":   handle_save,
    "raw":    handle_raw,
    "meta":   handle_meta,
    "links":  handle_links,
    "images": handle_images,
}


async def process_command(se_interface, args):
    if not args:
        se_interface.send_message(json.dumps({
            "status":  "error",
            "message": "No command or URL provided.",
            "usage": (
                "webpage_reader read <url> [--query <text>] | "
                "save <url> [--out <path>] [--query <text>] | "
                "raw <url> | meta <url> | "
                "links <url> [--internal-only | --external-only] | "
                "images <url>"
            ),
        }))
        return

    cmd = args[0].lower()

    if cmd in COMMANDS:
        result = await COMMANDS[cmd](args[1:])
    else:
        # bare URL → default LLM-friendly read
        result = await handle_read(args)

    print(result)
    se_interface.send_message(
        json.dumps(result, ensure_ascii=True).encode("utf-8").decode("utf-8")
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="WEBPAGE READER")
    soul_app.run_repl(main_fn=process_command)