import json
import sys
import re
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


class PdfReaderApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="SOUL PDF READER")

        self._commands = {
            "read": self._handle_read,
            "meta": self._handle_meta,
            "info": self._handle_info,
        }

    # ------------------------------------------------------------------ helpers

    def _resolve_path(self, raw: str) -> Path:
        p = Path(raw).expanduser()
        return p.resolve() if not p.is_absolute() else p

    def _parse_page_range(self, spec: str, total: int) -> list[int]:
        """Parse '3' or '1-5' into a 0-based list of page indices."""
        spec = spec.strip()
        if "-" in spec:
            parts = spec.split("-", 1)
            start = max(1, int(parts[0]))
            end   = min(total, int(parts[1]))
            return list(range(start - 1, end))
        else:
            n = int(spec)
            if 1 <= n <= total:
                return [n - 1]
            return []

    def _is_encrypted(self, path: Path) -> bool:
        if not PYPDF_AVAILABLE:
            return False
        try:
            r = PdfReader(str(path))
            return r.is_encrypted
        except Exception:
            return False

    def _extract_text_pypdf(self, path: Path, page_indices: list[int]) -> list[dict]:
        """Extract text per page using pypdf. Returns list of {page, text}."""
        reader = PdfReader(str(path))
        results = []
        for idx in page_indices:
            page = reader.pages[idx]
            text = page.extract_text() or ""
            results.append({"page": idx + 1, "text": text.strip()})
        return results

    def _extract_text_pdfplumber(self, path: Path, page_indices: list[int]) -> list[dict]:
        """Extract text per page using pdfplumber (better layout awareness)."""
        results = []
        with pdfplumber.open(str(path)) as pdf:
            for idx in page_indices:
                page = pdf.pages[idx]
                text = page.extract_text() or ""
                results.append({"page": idx + 1, "text": text.strip()})
        return results

    def _pages_to_markdown(self, pages: list[dict], numbered: bool) -> str:
        """Convert extracted page text dicts into LLM-readable Markdown."""
        chunks = []
        for entry in pages:
            page_num = entry["page"]
            text     = entry["text"]

            if not text:
                text = "_[No extractable text on this page — may be a scanned image or vector graphic.]_"

            # Light Markdown cleanup: preserve line breaks, strip excess whitespace
            cleaned = re.sub(r"\n{3,}", "\n\n", text)
            cleaned = re.sub(r" {2,}", " ", cleaned)

            if numbered:
                header = f"<!-- Page {page_num} -->\n\n"
            else:
                header = ""

            chunks.append(f"{header}{cleaned}")

        return "\n\n---\n\n".join(chunks)

    def _get_total_pages(self, path: Path) -> int | None:
        if PYPDF_AVAILABLE:
            try:
                return len(PdfReader(str(path)).pages)
            except Exception:
                pass
        if PDFPLUMBER_AVAILABLE:
            try:
                with pdfplumber.open(str(path)) as pdf:
                    return len(pdf.pages)
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ handlers

    def _handle_read(self, args: list) -> dict:
        if not args:
            return {
                "status":  "error",
                "message": "No file path provided.",
                "usage":   "read <path> [--pages 1-5 | --pages 3] [--numbered]",
            }

        # Parse flags
        numbered = "--numbered" in args
        args = [a for a in args if a != "--numbered"]

        pages_spec = None
        if "--pages" in args:
            idx = args.index("--pages")
            if idx + 1 < len(args):
                pages_spec = args[idx + 1]
                args = args[:idx] + args[idx + 2:]
            else:
                return {"status": "error", "message": "--pages flag requires a value (e.g. --pages 1-5)"}

        file_path = self._resolve_path(args[0])

        if not file_path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}
        if file_path.suffix.lower() != ".pdf":
            return {"status": "error", "message": f"Not a PDF file: {file_path.name}"}
        if self._is_encrypted(file_path):
            return {
                "status":  "encrypted",
                "message": "This PDF is password-protected. Provide the decrypted file to read.",
                "file":    str(file_path),
            }

        total = self._get_total_pages(file_path)
        if total is None:
            return {"status": "error", "message": "Could not determine page count. Ensure pypdf or pdfplumber is installed."}

        page_indices = self._parse_page_range(pages_spec, total) if pages_spec else list(range(total))
        if not page_indices:
            return {"status": "error", "message": f"Page range '{pages_spec}' is out of bounds for a {total}-page PDF."}

        # Prefer pdfplumber for richer layout; fall back to pypdf
        try:
            if PDFPLUMBER_AVAILABLE:
                pages = self._extract_text_pdfplumber(file_path, page_indices)
            elif PYPDF_AVAILABLE:
                pages = self._extract_text_pypdf(file_path, page_indices)
            else:
                return {
                    "status":  "error",
                    "message": "No PDF library available. Install pdfplumber or pypdf: pip install pdfplumber",
                }
        except Exception as e:
            return {"status": "error", "message": f"Extraction failed: {e}"}

        markdown = self._pages_to_markdown(pages, numbered)
        empty_pages = [p["page"] for p in pages if not p["text"] or "_[No extractable" in p["text"]]

        result = {
            "status":        "ok",
            "file":          str(file_path),
            "total_pages":   total,
            "pages_read":    [p["page"] for p in pages],
            "markdown":      markdown,
        }
        if empty_pages:
            result["warning"] = (
                f"Pages {empty_pages} had no extractable text — "
                "likely scanned or image-only. Consider OCR for these pages."
            )
        return result

    def _handle_meta(self, args: list) -> dict:
        if not args:
            return {"status": "error", "message": "No file path provided.", "usage": "meta <path>"}

        file_path = self._resolve_path(args[0])
        if not file_path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        if not PYPDF_AVAILABLE:
            return {"status": "error", "message": "pypdf not installed. Run: pip install pypdf"}

        try:
            reader = PdfReader(str(file_path))
            if reader.is_encrypted:
                return {"status": "encrypted", "message": "Cannot read metadata — PDF is password-protected."}

            meta = reader.metadata or {}
            total = len(reader.pages)

            return {
                "status":      "ok",
                "file":        str(file_path),
                "total_pages": total,
                "title":       meta.get("/Title", None),
                "author":      meta.get("/Author", None),
                "subject":     meta.get("/Subject", None),
                "creator":     meta.get("/Creator", None),
                "producer":    meta.get("/Producer", None),
                "created":     meta.get("/CreationDate", None),
                "modified":    meta.get("/ModDate", None),
                "markdown": (
                    f"---\n"
                    f"title: {meta.get('/Title', 'N/A')}\n"
                    f"author: {meta.get('/Author', 'N/A')}\n"
                    f"subject: {meta.get('/Subject', 'N/A')}\n"
                    f"creator: {meta.get('/Creator', 'N/A')}\n"
                    f"producer: {meta.get('/Producer', 'N/A')}\n"
                    f"created: {meta.get('/CreationDate', 'N/A')}\n"
                    f"modified: {meta.get('/ModDate', 'N/A')}\n"
                    f"pages: {total}\n"
                    f"---"
                ),
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to read metadata: {e}"}

    def _handle_info(self, args: list) -> dict:
        if not args:
            return {"status": "error", "message": "No file path provided.", "usage": "info <path>"}

        file_path = self._resolve_path(args[0])
        if not file_path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}
        if file_path.suffix.lower() != ".pdf":
            return {"status": "error", "message": f"Not a PDF file: {file_path.name}"}

        size_bytes = file_path.stat().st_size
        size_kb    = round(size_bytes / 1024, 2)

        encrypted  = self._is_encrypted(file_path)
        total      = None if encrypted else self._get_total_pages(file_path)

        # Quick text probe on page 1 to detect scanned PDFs
        text_extractable = False
        if not encrypted and total and PYPDF_AVAILABLE:
            try:
                sample = PdfReader(str(file_path)).pages[0].extract_text() or ""
                text_extractable = bool(sample.strip())
            except Exception:
                pass

        return {
            "status":           "ok",
            "file":             str(file_path),
            "file_name":        file_path.name,
            "size_bytes":       size_bytes,
            "size_kb":          size_kb,
            "total_pages":      total,
            "encrypted":        encrypted,
            "text_extractable": text_extractable,
            "likely_scanned":   (not text_extractable and not encrypted and total is not None),
            "markdown": (
                f"## PDF Info: `{file_path.name}`\n\n"
                f"| Field | Value |\n"
                f"|---|---|\n"
                f"| Size | {size_kb} KB ({size_bytes} bytes) |\n"
                f"| Pages | {total if total is not None else 'Unknown (encrypted)'} |\n"
                f"| Encrypted | {'Yes ⚠️' if encrypted else 'No'} |\n"
                f"| Text Extractable | {'Yes ✅' if text_extractable else 'No — likely scanned ⚠️'} |\n"
            ),
        }

    # ------------------------------------------------------------------ entry

    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "No command provided.",
                "usage":   (
                    "pdf_reader_app read <path> [--pages 1-5] [--numbered] | "
                    "meta <path> | "
                    "info <path>"
                ),
            }))
            return

        cmd = args[0].lower()
        if cmd in self._commands:
            result = self._commands[cmd](args[1:])
        else:
            # Assume bare path → read the whole file
            result = self._handle_read(args)

        se_interface.send_message(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    app = PdfReaderApp()
    app.run_one_shot()