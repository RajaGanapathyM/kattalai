"""
Soul Vision App  (Simplified)
──────────────────────────────
Local image understanding via Ollama. Zero binary installs, zero auth.

Dependencies  (pip install only):
    pip install Pillow opencv-python requests

Requires Ollama running with a vision model:
    ollama pull llava          # ~4 GB, one-time
    ollama serve               # usually already running for Kattalai

Actions
───────
  screenshot    → captures screen  → Ollama vision  → saves + returns JSON
  camera        → webcam capture   → Ollama vision  → saves + returns JSON
  ocr           → image from path  → OCR prompt     → saves + returns JSON
  ask           → image from path  → custom question → saves + returns JSON
  extract_table → image from path  → table prompt   → saves .csv + returns JSON

Permission dialog is shown once per sensitive action (screenshot / camera).
Everything else runs automatically — no file pickers, no save dialogs.
Results auto-saved to ~/vision_results/.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import scrolledtext
import tkinter as tk

# ── path bootstrap ─────────────────────────────────────────────────────────────
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
from se_app_utils.soulengine import soul_engine_app  # noqa: E402

# ── optional deps (graceful degradation) ──────────────────────────────────────
try:
    from PIL import Image, ImageTk, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ── constants ──────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL     = "http://localhost:11434"
OLLAMA_CHAT_URL     = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_VISION_MODEL = "moondream"      # moondream = fastest on CPU; llava-phi3 = better quality
OLLAMA_TIMEOUT      = 120              # seconds

DEFAULT_OUTPUT     = Path.home() / "vision_results"
IMAGE_EXTENSIONS   = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")
CAMERA_COUNTDOWN_S = 3
DEFAULT_CAMERA_ID  = 0

ACT_SCREENSHOT    = "screenshot"
ACT_CAMERA        = "camera"
ACT_OCR           = "ocr"
ACT_ASK           = "ask"
ACT_EXTRACT_TABLE = "extract_table"

ACTION_LABELS = {
    ACT_SCREENSHOT:    "📸  CAPTURE SCREEN",
    ACT_CAMERA:        "📷  CAMERA CAPTURE",
    ACT_OCR:           "🔍  EXTRACT TEXT",
    ACT_ASK:           "🤖  VISUAL Q&A",
    ACT_EXTRACT_TABLE: "📊  EXTRACT TABLE",
}

OCR_PROMPT   = (
    "Extract every piece of text visible in this image exactly as written. "
    "Preserve line breaks. Output only the extracted text, nothing else."
)
TABLE_PROMPT = (
    "Extract all table data from this image. "
    "Output each row as pipe-separated values (one row per line). "
    "Put column headers on the first line if visible. "
    "Output only the table data, nothing else."
)
DESCRIBE_PROMPT = "Describe this image in detail."

# ── palette ────────────────────────────────────────────────────────────────────
BG        = "#0d1117"
PANEL     = "#161b22"
BORDER    = "#30363d"
GREEN     = "#3fb950"
GREEN_DIM = "#1a4d25"
RED_LIVE  = "#f85149"
AMBER     = "#d29922"
FG        = "#e6edf3"
FG_DIM    = "#8b949e"
MONO      = ("Courier New", 9)
SANS      = ("Helvetica", 11)


# ══════════════════════════════════════════════════════════════════════════════
#  Ollama helpers
# ══════════════════════════════════════════════════════════════════════════════

def _pil_to_b64(img: "Image.Image") -> str:
    """Encode PIL image as base64 PNG string for Ollama."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _ollama_vision(img: "Image.Image", prompt: str) -> str:
    """
    Send image + prompt to Ollama via /api/chat (messages format).

    Why /api/chat and not /api/generate?
    - /api/generate with a flat 'prompt' field causes moondream (and some
      llava variants) to ignore the question and just describe the image.
    - /api/chat passes the prompt as a proper user message alongside the
      image, which all Ollama vision models handle correctly.
    """
    if not REQUESTS_AVAILABLE:
        raise RuntimeError(
            "requests not installed.\n"
            "Run: pip install requests"
        )

    payload = {
        "model": OLLAMA_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [_pil_to_b64(img)],
            }
        ],
        "stream": False,
    }
    # print(f"Sending image to Ollama with prompt: {prompt[:60]}...")

    try:
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}.\n"
            "Make sure Ollama is running:  ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama timed out after {OLLAMA_TIMEOUT}s. "
            "Try a smaller/faster model or increase OLLAMA_TIMEOUT."
        )

    if resp.status_code == 404:
        raise RuntimeError(
            f"Vision model '{OLLAMA_VISION_MODEL}' not found in Ollama.\n"
            f"Pull it first:  ollama pull {OLLAMA_VISION_MODEL}"
        )
    if not resp.ok:
        raise RuntimeError(
            f"Ollama error {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    # /api/chat returns data["message"]["content"]
    # (unlike /api/generate which uses data["response"])
    return data.get("message", {}).get("content", "").strip()


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════

class VisionGUI:
    """
    Minimal automated GUI.
    1. Permission dialog  (screenshot / camera only, once per action call).
    2. Small progress window while Ollama processes in the background.
    3. Auto-saves result → closes.
    """

    def __init__(
        self,
        action: str = ACT_ASK,
        image_path: "Path | None" = None,
        question: "str | None" = None,
        output_path: "str | None" = None,
        camera_id: int = DEFAULT_CAMERA_ID,
    ):
        self.action      = action
        self.image_path  = Path(image_path).expanduser().resolve() if image_path else None
        self.question    = question or ""
        self.output_path = Path(output_path) if output_path else None
        self.camera_id   = camera_id
        self.session_id  = str(uuid.uuid4())
        self.result: dict = {}

        self._pil_image: "Image.Image | None" = None
        self._cap:       "cv2.VideoCapture | None" = None
        self._camera_active  = False
        self._countdown_left = CAMERA_COUNTDOWN_S
        self._last_frame: "Image.Image | None" = None

    # ── entry point ────────────────────────────────────────────────────────────

    def run(self) -> dict:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Soul Vision")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # dependency check
        missing = []
        if not PIL_AVAILABLE:
            missing.append("Pillow  →  pip install Pillow")
        if self.action == ACT_CAMERA and not CV2_AVAILABLE:
            missing.append("opencv-python  →  pip install opencv-python")
        if not REQUESTS_AVAILABLE:
            missing.append("requests  →  pip install requests")
        if missing:
            self.root.destroy()
            return {
                "status":  "error",
                "message": "Missing dependencies:\n" + "\n".join(missing),
            }

        # permission dialog for capture actions
        if self.action == ACT_SCREENSHOT:
            if not self._permission_dialog(
                "📸  SCREENSHOT ACCESS REQUEST",
                "Soul Vision wants to capture your screen.\n"
                "Processing is entirely local — nothing is uploaded.",
            ):
                self.root.destroy()
                return {"status": "cancelled", "message": "User denied screenshot permission."}

        elif self.action == ACT_CAMERA:
            if not self._permission_dialog(
                "📷  CAMERA ACCESS REQUEST",
                "Soul Vision wants to access your webcam.\n"
                "Processing is entirely local — nothing is uploaded.",
            ):
                self.root.destroy()
                return {"status": "cancelled", "message": "User denied camera permission."}

        self._build_progress_window()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.after(120, self._start)
        self.root.mainloop()
        return self.result

    # ── permission dialog ──────────────────────────────────────────────────────

    def _permission_dialog(self, title_text: str, body_text: str) -> bool:
        dlg = tk.Toplevel(self.root)
        dlg.title("Permission Required")
        dlg.geometry("460x230")
        dlg.configure(bg=BG)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

        allowed = [False]

        tk.Label(
            dlg, text=f"  {title_text}",
            font=("Helvetica", 13, "bold"), bg=BG, fg=GREEN, anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 4))

        sid_row = tk.Frame(dlg, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        sid_row.pack(fill="x", padx=24, pady=4)
        tk.Label(
            sid_row, text=f"  Session  {self.session_id}",
            font=MONO, bg=PANEL, fg=AMBER, anchor="w",
        ).pack(fill="x", padx=6, pady=6)

        tk.Label(
            dlg, text=body_text,
            font=SANS, bg=BG, fg=FG, justify="left",
        ).pack(padx=24, pady=8, anchor="w")

        bf = tk.Frame(dlg, bg=BG)
        bf.pack(pady=10)

        def _allow():
            allowed[0] = True
            dlg.destroy()

        _btn(bf, "✓  Allow", _allow,     GREEN_DIM, GREEN   ).pack(side="left", padx=10)
        _btn(bf, "✗  Deny",  dlg.destroy, "#3d1a1a", RED_LIVE).pack(side="left", padx=10)

        self.root.wait_window(dlg)
        return allowed[0]

    # ── progress window ────────────────────────────────────────────────────────

    def _build_progress_window(self):
        needs_preview = self.action in (ACT_SCREENSHOT, ACT_CAMERA)
        h = 420 if needs_preview else 240
        self.root.geometry(f"500x{h}")

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(
            top, text=f"◉  {ACTION_LABELS.get(self.action, '🖼  SOUL VISION')}",
            font=("Helvetica", 14, "bold"), bg=BG, fg=GREEN,
        ).pack(side="left")
        tk.Label(top, text=self.session_id[:12], font=MONO, bg=BG, fg=FG_DIM).pack(side="right")

        self._status_lbl = tk.Label(
            self.root, text="⏳  Starting…",
            font=SANS, bg=BG, fg=AMBER, anchor="w",
        )
        self._status_lbl.pack(fill="x", padx=20, pady=2)

        # preview panel
        self._preview_lbl = None
        if needs_preview:
            pf = tk.Frame(self.root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            pf.pack(fill="both", expand=True, padx=20, pady=4)
            self._preview_lbl = tk.Label(pf, bg=PANEL, fg=FG_DIM, font=SANS, text="preview…")
            self._preview_lbl.pack(fill="both", expand=True, padx=6, pady=6)

        # result box
        rf = tk.Frame(self.root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        rf.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        rh = tk.Frame(rf, bg=PANEL)
        rh.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(rh, text="RESULT", font=MONO, bg=PANEL, fg=FG_DIM).pack(side="left")
        self._char_lbl = tk.Label(rh, text="", font=MONO, bg=PANEL, fg=FG_DIM)
        self._char_lbl.pack(side="right")

        self._result_box = scrolledtext.ScrolledText(
            rf, wrap=tk.WORD, font=("Helvetica", 10),
            bg=PANEL, fg=FG, insertbackground=GREEN,
            relief="flat", state="disabled", padx=8, pady=6, height=5,
        )
        self._result_box.pack(fill="both", expand=True, padx=4, pady=(2, 8))

    # ── orchestration ──────────────────────────────────────────────────────────

    def _start(self):
        if self.action == ACT_SCREENSHOT:
            self._do_screenshot()
        elif self.action == ACT_CAMERA:
            self._do_camera()
        else:
            threading.Thread(target=self._flow_file, daemon=True).start()

    # ── screenshot ─────────────────────────────────────────────────────────────

    def _do_screenshot(self):
        self._set_status("📸  Capturing screen…", AMBER)
        self.root.withdraw()
        self.root.after(350, self._grab_screen)

    def _grab_screen(self):
        try:
            shot = ImageGrab.grab()
            self.root.deiconify()
            self._pil_image = shot
            self._render_preview(shot)
            self._set_status(f"✅  Captured {shot.width}×{shot.height} — sending to Ollama…", GREEN)
            threading.Thread(target=self._flow_run, daemon=True).start()
        except Exception as exc:
            self.root.deiconify()
            self._finish_error(f"Screen capture failed: {exc}")

    # ── camera ─────────────────────────────────────────────────────────────────

    def _do_camera(self):
        if not CV2_AVAILABLE:
            self._finish_error("opencv-python not installed — run: pip install opencv-python")
            return
        try:
            self._cap = cv2.VideoCapture(self.camera_id)
            if not self._cap.isOpened():
                self._finish_error(f"Cannot open camera {self.camera_id}.")
                return
            self._camera_active  = True
            self._countdown_left = CAMERA_COUNTDOWN_S
            self._camera_tick()
        except Exception as exc:
            self._finish_error(f"Camera error: {exc}")

    def _camera_tick(self):
        if not self._camera_active:
            return
        ret, frame = self._cap.read() if self._cap else (False, None)
        if ret and frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._last_frame = Image.fromarray(rgb)
            self._render_preview(self._last_frame)

        if self._countdown_left > 0:
            self._set_status(f"🔴  Auto-capturing in {self._countdown_left}s…", RED_LIVE)
            self._countdown_left -= 1
            self.root.after(1000, self._camera_tick)
        else:
            self._camera_active = False
            self._release_camera()
            img = self._last_frame
            if img is None:
                self._finish_error("No frame from camera.")
                return
            self._pil_image = img
            self._set_status("✅  Frame captured — sending to Ollama…", GREEN)
            threading.Thread(target=self._flow_run, daemon=True).start()

    def _release_camera(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    # ── file-based flow ────────────────────────────────────────────────────────

    def _flow_file(self):
        try:
            if not self.image_path or not self.image_path.exists():
                raise RuntimeError(f"Image not found: {self.image_path}")
            self.root.after(0, lambda: self._set_status("🔍  Loading image…", AMBER))
            self._pil_image = Image.open(self.image_path)
            self._flow_run()
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._finish_error(str(e)))

    def _flow_run(self):
        """Pick the right prompt and call Ollama, then finish."""
        try:
            self.root.after(0, lambda: self._set_status(
                f"⚙️  Sending to Ollama ({OLLAMA_VISION_MODEL})…", AMBER))
            prompt = self._pick_prompt()
            result = _ollama_vision(self._pil_image, prompt)
            self.root.after(0, lambda r=result: self._finish_ok(r))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._finish_error(str(e)))

    def _pick_prompt(self) -> str:
        if self.action == ACT_OCR:
            return OCR_PROMPT
        if self.action == ACT_EXTRACT_TABLE:
            return TABLE_PROMPT
        if self.action == ACT_ASK and self.question:
            return self.question
        if self.action == ACT_SCREENSHOT and self.question:
            return self.question
        if self.action == ACT_CAMERA and self.question:
            return self.question
        return DESCRIBE_PROMPT

    # ── finish ─────────────────────────────────────────────────────────────────

    def _finish_ok(self, text: str):
        self._result_box.config(state="normal")
        self._result_box.delete("1.0", tk.END)
        self._result_box.insert(tk.END, text)
        self._result_box.config(state="disabled")
        self._char_lbl.config(text=f"{len(text)} chars")
        self._set_status("✅  Done — saving…", GREEN)

        save_path = self._auto_save(text)
        if save_path:
            self._set_status(f"💾  Saved → {save_path.name}", GREEN)

        self.result = {
            "status":     "ok",
            "action":     self.action,
            "session_id": self.session_id,
            "model":      OLLAMA_VISION_MODEL,
            "file":       str(save_path) if save_path else None,
            "char_count": len(text),
            "image":      str(self.image_path) if self.image_path else None,
            "preview":    text[:300],
            "markdown": (
                f"## Vision result: `{self.action}`\n\n"
                f"- **Model**: `{OLLAMA_VISION_MODEL}`\n"
                f"- **File**: `{save_path}`\n"
                f"- **Image**: `{self.image_path}`\n"
                f"- **Chars**: {len(text)}\n"
                f"- **Session**: `{self.session_id}`\n\n"
                f"---\n\n{text[:500]}"
                + ("…" if len(text) > 500 else "")
            ),
        }
        self.root.after(1400, self.root.destroy)

    def _finish_error(self, msg: str):
        self._set_status(f"❌  {msg[:80]}", RED_LIVE)
        self.result = {"status": "error", "message": msg, "session_id": self.session_id}
        self.root.after(3000, self.root.destroy)

    def _auto_save(self, text: str) -> "Path | None":
        if self.output_path:
            save_path = self.output_path
        else:
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "csv" if self.action == ACT_EXTRACT_TABLE else "txt"
            save_path = DEFAULT_OUTPUT / f"vision_{self.action}_{ts}.{ext}"
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(text, encoding="utf-8")
            return save_path
        except Exception as exc:
            self._set_status(f"⚠️  Save failed: {exc}", AMBER)
            return None

    # ── UI helpers ─────────────────────────────────────────────────────────────

    def _render_preview(self, img: "Image.Image"):
        if self._preview_lbl is None:
            return
        try:
            display = img.copy()
            display.thumbnail((460, 220))
            photo = ImageTk.PhotoImage(display)
            self._preview_lbl.config(image=photo, text="")
            self._preview_lbl.image = photo          # keep reference
        except Exception:
            pass

    def _set_status(self, text: str, color: str = FG):
        if hasattr(self, "_status_lbl"):
            self._status_lbl.config(text=text, fg=color)

    def _on_close(self):
        self._camera_active = False
        self._release_camera()
        if not self.result:
            self.result = {"status": "cancelled", "message": "Window closed by user."}
        self.root.destroy()


# ── widget helper ──────────────────────────────────────────────────────────────

def _btn(parent, text: str, cmd, bg: str, fg: str) -> tk.Button:
    return tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, font=("Helvetica", 11, "bold"),
        relief="flat", cursor="hand2",
        activebackground=bg, activeforeground=fg,
        padx=14, pady=7,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Soul Engine App wrapper
# ══════════════════════════════════════════════════════════════════════════════

class VisionApp(soul_engine_app):

    def __init__(self):
        super().__init__(app_name="SOUL VISION")
        self._commands = {
            "screenshot":    self._handle_screenshot,
            "capture":       self._handle_screenshot,
            "camera":        self._handle_camera,
            "webcam":        self._handle_camera,
            "photo":         self._handle_camera,
            "cam":           self._handle_camera,
            "ocr":           self._handle_ocr,
            "read":          self._handle_ocr,
            "read_image":    self._handle_ocr,
            "ask":           self._handle_ask,
            "vision":        self._handle_ask,
            "query":         self._handle_ask,
            "describe":      self._handle_ask,
            "extract_table": self._handle_extract_table,
            "table":         self._handle_extract_table,
        }

    # ── argument parsers ───────────────────────────────────────────────────────
    #
    # The soul engine splits the command string on spaces before passing args,
    # so multi-word questions like "What is the error?" arrive as separate
    # tokens: ["What", "is", "the", "error?"].
    #
    # Strategy:
    #   • --output=<path>  and  --camera=N  are single-token flags (pop first).
    #   • The first token whose suffix matches IMAGE_EXTENSIONS is the image path.
    #   • Every remaining non-flag token is joined with spaces → the question.
    #   • There is NO --question= flag; it would always be truncated.

    @staticmethod
    def _pop_image_path(args: list) -> "tuple[Path | None, list]":
        """Remove and return the first image-file token from args."""
        remaining, image_path = [], None
        for arg in args:
            if (
                not arg.startswith("--")
                and Path(arg).suffix.lower() in IMAGE_EXTENSIONS
                and image_path is None
            ):
                image_path = Path(arg).expanduser().resolve()
            else:
                remaining.append(arg)
        return image_path, remaining

    @staticmethod
    def _pop_flag(args: list, flag: str) -> "tuple[str | None, list]":
        """Remove and return --flag=value (single-token, no spaces in value)."""
        remaining, value = [], None
        for arg in args:
            if arg.startswith(f"--{flag}="):
                value = arg.split("=", 1)[1]
            else:
                remaining.append(arg)
        return value, remaining

    @staticmethod
    def _rest_as_question(args: list) -> "str | None":
        """Join all remaining non-flag tokens as a single question string."""
        words = [a for a in args if not a.startswith("--")]
        return " ".join(words).strip() or None

    # ── handlers ───────────────────────────────────────────────────────────────

    def _handle_screenshot(self, args: list) -> dict:
        output_path, args = self._pop_flag(args, "output")
        question          = self._rest_as_question(args)   # all remaining words
        return VisionGUI(action=ACT_SCREENSHOT, question=question,
                         output_path=output_path).run()

    def _handle_camera(self, args: list) -> dict:
        output_path, args = self._pop_flag(args, "output")
        camera_id_s, args = self._pop_flag(args, "camera")
        question          = self._rest_as_question(args)
        return VisionGUI(action=ACT_CAMERA, question=question,
                         output_path=output_path,
                         camera_id=int(camera_id_s) if camera_id_s else DEFAULT_CAMERA_ID
                         ).run()

    def _handle_ocr(self, args: list) -> dict:
        image_path,  args = self._pop_image_path(args)
        output_path, _    = self._pop_flag(args, "output")
        return VisionGUI(action=ACT_OCR, image_path=image_path,
                         output_path=output_path).run()

    def _handle_ask(self, args: list) -> dict:
        image_path,  args = self._pop_image_path(args)
        output_path, args = self._pop_flag(args, "output")
        question          = self._rest_as_question(args)   # all remaining words = question
        return VisionGUI(action=ACT_ASK, image_path=image_path,
                         question=question, output_path=output_path).run()

    def _handle_extract_table(self, args: list) -> dict:
        image_path,  args = self._pop_image_path(args)
        output_path, _    = self._pop_flag(args, "output")
        return VisionGUI(action=ACT_EXTRACT_TABLE, image_path=image_path,
                         output_path=output_path).run()

    async def process_command(self, se_interface, args):
        if not args:
            cmd, cmd_args = "ask", []
        else:
            cmd      = args[0].lower()
            cmd_args = args[1:]
        handler = self._commands.get(cmd)
        result  = handler(cmd_args) if handler else self._handle_ask(args)
        se_interface.send_message(json.dumps(result, ensure_ascii=False))


# ── standalone ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    VisionApp().run_one_shot()