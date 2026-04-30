"""
Soul Transcription App
─────────────────────
Local speech-to-text using faster-whisper (base model, int8-quantised).
Presents a tkinter GUI with:
  1. GUID-keyed permission dialog before microphone access
  2. Live rolling transcription display during recording
  3. GUID-keyed save-permission dialog before writing to disk

Returns a JSON result via soul_engine_app.send_message.

Dependencies (install once):
    pip install faster-whisper sounddevice numpy
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import scrolledtext, messagebox, font as tkfont

# ── Path bootstrap ────────────────────────────────────────────────────────────
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
from se_app_utils.soulengine import soul_engine_app  # noqa: E402

# ── Optional heavy deps ───────────────────────────────────────────────────────
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 16_000          # Hz  – Whisper native sample rate
CHUNK_SECONDS  = 4               # seconds per live-transcription chunk
MODEL_SIZE     = "base"          # tiny / base / small — base is best speed/quality balance
DEFAULT_OUTPUT = Path.home() / "transcriptions"

# ── Palette (dark terminal-green aesthetic) ───────────────────────────────────
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
SANS_B    = ("Helvetica", 11, "bold")


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════════════════════════

class TranscriptionGUI:
    """Full-lifecycle tkinter GUI for one recording+transcription session."""

    def __init__(self, output_path: Path | None = None):
        self.session_id   = str(uuid.uuid4())
        self.output_path  = output_path
        self.result: dict = {}

        # Runtime state
        self.recording       = False
        self.model: "WhisperModel | None" = None
        self._audio_buffer   : list       = []
        self._pending_buffer : list       = []   # accumulates during chunk gap
        self._tx_queue       : queue.Queue[str] = queue.Queue()
        self._full_text      : list[str]        = []
        self._record_thread  : threading.Thread | None = None
        self._model_ready    = threading.Event()

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        """Block until session complete, return result dict."""
        self.root = tk.Tk()
        self.root.withdraw()                # hidden until permission granted
        self.root.title("Soul Transcription")
        self.root.geometry("640x520")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── dep check ─────────────────────────────────────────────────────────
        if not AUDIO_AVAILABLE or not WHISPER_AVAILABLE:
            missing = []
            if not AUDIO_AVAILABLE:  missing.append("sounddevice numpy")
            if not WHISPER_AVAILABLE: missing.append("faster-whisper")
            return {
                "status":  "error",
                "message": f"Missing dependencies: {', '.join(missing)}. "
                           f"Run: pip install {' '.join(missing)}",
            }

        # ── step 1: permission dialog ─────────────────────────────────────────
        if not self._ask_record_permission():
            self.root.destroy()
            return {"status": "cancelled", "message": "User denied microphone permission."}

        # ── step 2: build main UI then show window ────────────────────────────
        self._build_ui()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

        # ── step 3: load model in background ─────────────────────────────────
        threading.Thread(target=self._load_model_bg, daemon=True).start()

        self.root.mainloop()
        return self.result

    # ── permission dialogs ────────────────────────────────────────────────────

    def _ask_record_permission(self) -> bool:
        dlg = tk.Toplevel(self.root)
        dlg.title("Microphone Permission")
        dlg.geometry("460x260")
        dlg.configure(bg=BG)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

        allowed = [False]

        # Header
        tk.Label(dlg, text="  🎙  MICROPHONE ACCESS REQUEST",
                 font=("Helvetica", 13, "bold"), bg=BG, fg=GREEN,
                 anchor="w").pack(fill="x", padx=24, pady=(24, 4))

        # Session GUID
        _frame(dlg, bg=PANEL, bd=1, relief="flat").pack(fill="x", padx=24, pady=4)
        inner = _frame(dlg.winfo_children()[-1], bg=PANEL)
        inner.pack(padx=10, pady=8, fill="x")
        tk.Label(inner, text="Session ID", font=MONO, bg=PANEL, fg=FG_DIM).pack(anchor="w")
        tk.Label(inner, text=self.session_id,
                 font=MONO, bg=PANEL, fg=AMBER, wraplength=400, anchor="w").pack(anchor="w")

        tk.Label(dlg,
                 text="Soul Transcription requests microphone access\nto record and transcribe your audio locally.",
                 font=SANS, bg=BG, fg=FG, justify="left").pack(padx=24, pady=10, anchor="w")

        # Buttons
        bf = _frame(dlg, bg=BG)
        bf.pack(pady=10)

        def _allow():
            allowed[0] = True
            dlg.destroy()

        _btn(bf, "✓  Allow Recording", _allow, GREEN_DIM, GREEN).pack(side="left", padx=8)
        _btn(bf, "✗  Deny",            dlg.destroy, "#3d1a1a", RED_LIVE).pack(side="left", padx=8)

        self.root.wait_window(dlg)
        return allowed[0]

    def _ask_save_permission(self, preview: str, save_path: Path) -> bool:
        dlg = tk.Toplevel(self.root)
        dlg.title("Save Permission")
        dlg.geometry("460x300")
        dlg.configure(bg=BG)
        dlg.grab_set()
        dlg.resizable(False, False)

        confirmed = [False]

        tk.Label(dlg, text="  💾  SAVE TRANSCRIPTION",
                 font=("Helvetica", 13, "bold"), bg=BG, fg=GREEN,
                 anchor="w").pack(fill="x", padx=24, pady=(24, 4))

        # GUID row
        _frame(dlg, bg=PANEL, bd=1, relief="flat").pack(fill="x", padx=24, pady=4)
        inner = _frame(dlg.winfo_children()[-1], bg=PANEL)
        inner.pack(padx=10, pady=6, fill="x")
        tk.Label(inner, text="Session ID", font=MONO, bg=PANEL, fg=FG_DIM).pack(anchor="w")
        tk.Label(inner, text=self.session_id,
                 font=MONO, bg=PANEL, fg=AMBER).pack(anchor="w")

        # Path
        tk.Label(dlg, text=f"Output path:\n{save_path}",
                 font=MONO, bg=BG, fg=FG_DIM, justify="left",
                 wraplength=400).pack(padx=24, pady=(6, 2), anchor="w")

        # Preview
        pv = preview[:120] + ("…" if len(preview) > 120 else "")
        tk.Label(dlg, text=f'Preview: "{pv}"',
                 font=("Helvetica", 10, "italic"), bg=BG, fg=FG,
                 wraplength=400, justify="left").pack(padx=24, pady=4, anchor="w")

        bf = _frame(dlg, bg=BG)
        bf.pack(pady=12)

        def _confirm():
            confirmed[0] = True
            dlg.destroy()

        _btn(bf, "✓  Save File",   _confirm,    GREEN_DIM, GREEN).pack(side="left", padx=8)
        _btn(bf, "✗  Cancel",      dlg.destroy, "#3d1a1a", RED_LIVE).pack(side="left", padx=8)

        self.root.wait_window(dlg)
        return confirmed[0]

    # ── main UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = self.root

        # ── top bar ───────────────────────────────────────────────────────────
        top = _frame(root, bg=BG)
        top.pack(fill="x", padx=20, pady=(18, 6))

        tk.Label(top, text="◉  SOUL TRANSCRIPTION",
                 font=("Helvetica", 15, "bold"), bg=BG, fg=GREEN).pack(side="left")

        self._session_lbl = tk.Label(
            top, text=f"session:{self.session_id[:12]}",
            font=MONO, bg=BG, fg=FG_DIM)
        self._session_lbl.pack(side="right")

        # ── status bar ────────────────────────────────────────────────────────
        self._status_lbl = tk.Label(
            root, text="⏳  Loading model…",
            font=SANS, bg=BG, fg=AMBER, anchor="w")
        self._status_lbl.pack(fill="x", padx=20, pady=2)

        # ── live transcript panel ─────────────────────────────────────────────
        panel = tk.Frame(root, bg=PANEL, bd=0, highlightbackground=BORDER,
                         highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=20, pady=6)

        header = _frame(panel, bg=PANEL)
        header.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(header, text="LIVE TRANSCRIPT", font=MONO, bg=PANEL, fg=FG_DIM).pack(side="left")
        self._word_count_lbl = tk.Label(header, text="0 words",
                                         font=MONO, bg=PANEL, fg=FG_DIM)
        self._word_count_lbl.pack(side="right")

        self._tx_box = scrolledtext.ScrolledText(
            panel, wrap=tk.WORD,
            font=("Helvetica", 12),
            bg=PANEL, fg=FG,
            insertbackground=GREEN,
            selectbackground=GREEN_DIM,
            relief="flat",
            state="disabled",
            padx=10, pady=8,
        )
        self._tx_box.pack(fill="both", expand=True, padx=4, pady=(4, 8))

        # ── pulse indicator ───────────────────────────────────────────────────
        self._pulse_canvas = tk.Canvas(root, width=640, height=30,
                                        bg=BG, highlightthickness=0)
        self._pulse_canvas.pack(fill="x", padx=20)
        self._pulse_bars = []
        for i in range(32):
            x = 8 + i * 19
            bar = self._pulse_canvas.create_rectangle(
                x, 15, x+12, 15, fill=GREEN_DIM, outline="")
            self._pulse_bars.append(bar)

        # ── control buttons ───────────────────────────────────────────────────
        bf = _frame(root, bg=BG)
        bf.pack(pady=14)

        self._rec_btn = _btn(bf, "⏺  Start Recording",
                              self._toggle_recording,
                              GREEN_DIM, GREEN, width=18)
        self._rec_btn.pack(side="left", padx=10)
        self._rec_btn.config(state="disabled")   # enabled after model loads

        self._save_btn = _btn(bf, "💾  Save",
                               self._do_save,
                               "#1a1e26", FG_DIM, width=10)
        self._save_btn.pack(side="left", padx=10)
        self._save_btn.config(state="disabled")

    # ── model loading ─────────────────────────────────────────────────────────

    def _load_model_bg(self):
        try:
            self.model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
            self._model_ready.set()
            self.root.after(0, self._on_model_ready)
        except Exception as exc:
            self.root.after(0, lambda: self._fatal(f"Model load failed: {exc}"))

    def _on_model_ready(self):
        self._set_status("✅  Model ready — press Start to record", GREEN)
        self._rec_btn.config(state="normal")

    # ── recording ─────────────────────────────────────────────────────────────

    def _toggle_recording(self):
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        self.recording = True
        self._audio_buffer.clear()
        self._pending_buffer.clear()
        self._rec_btn.config(text="⏹  Stop Recording",
                             bg=RED_LIVE, fg="white")
        self._save_btn.config(state="disabled", bg="#1a1e26", fg=FG_DIM)
        self._set_status("🔴  Recording…  (live transcription active)", RED_LIVE)
        self._record_thread = threading.Thread(
            target=self._recording_worker, daemon=True)
        self._record_thread.start()
        self.root.after(200, self._poll_transcript)
        self.root.after(100, self._animate_pulse)

    def _stop_recording(self):
        self.recording = False
        self._rec_btn.config(text="⏺  Start Recording",
                             bg=GREEN_DIM, fg=GREEN)
        self._set_status("✅  Recording stopped — review and save", GREEN)
        self._save_btn.config(state="normal", bg=GREEN_DIM, fg=GREEN)
        self._reset_pulse()

    def _recording_worker(self):
        """Stream mic → chunk queue → transcribe → text queue."""
        chunk_frames = SAMPLE_RATE * CHUNK_SECONDS
        buf: list = []

        def _callback(indata, frames, time_info, status):
            if self.recording:
                buf.append(indata.copy())

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="float32", callback=_callback):
                while self.recording:
                    time.sleep(CHUNK_SECONDS)
                    if buf:
                        chunk = np.concatenate(buf, axis=0).flatten()
                        buf.clear()
                        self._audio_buffer.append(chunk)
                        threading.Thread(target=self._transcribe_chunk,
                                         args=(chunk,), daemon=True).start()

            # Drain remaining buffer after stop
            if buf:
                chunk = np.concatenate(buf, axis=0).flatten()
                self._audio_buffer.append(chunk)
                text = self._do_transcribe(chunk)
                if text:
                    self._tx_queue.put(text)

        except Exception as exc:
            self._tx_queue.put(f"\n[Recording error: {exc}]\n")

    def _transcribe_chunk(self, audio: "np.ndarray"):
        text = self._do_transcribe(audio)
        if text:
            self._tx_queue.put(text)

    def _do_transcribe(self, audio: "np.ndarray") -> str:
        if self.model is None:
            return ""
        try:
            # beam_size=1 → greedy decode, fastest
            segments, _ = self.model.transcribe(
                audio, beam_size=1, language=None, vad_filter=True)
            return " ".join(seg.text for seg in segments).strip()
        except Exception:
            return ""

    # ── live UI updates ───────────────────────────────────────────────────────

    def _poll_transcript(self):
        updated = False
        try:
            while True:
                text = self._tx_queue.get_nowait()
                if text:
                    self._full_text.append(text)
                    self._tx_box.config(state="normal")
                    self._tx_box.insert(tk.END, text + " ")
                    self._tx_box.see(tk.END)
                    self._tx_box.config(state="disabled")
                    updated = True
        except queue.Empty:
            pass

        if updated:
            total_words = len(" ".join(self._full_text).split())
            self._word_count_lbl.config(text=f"{total_words} words")

        if self.recording or not self._tx_queue.empty():
            self.root.after(200, self._poll_transcript)

    def _animate_pulse(self):
        if not self.recording:
            return
        import random
        for bar in self._pulse_bars:
            h = random.randint(2, 22)
            self._pulse_canvas.coords(bar,
                self._pulse_canvas.coords(bar)[0], 15 - h // 2,
                self._pulse_canvas.coords(bar)[2], 15 + h // 2)
            self._pulse_canvas.itemconfig(
                bar, fill=GREEN if h > 10 else GREEN_DIM)
        self.root.after(80, self._animate_pulse)

    def _reset_pulse(self):
        for bar in self._pulse_bars:
            x0, _, x1, _ = self._pulse_canvas.coords(bar)
            self._pulse_canvas.coords(bar, x0, 15, x1, 15)
            self._pulse_canvas.itemconfig(bar, fill=GREEN_DIM)

    # ── save ──────────────────────────────────────────────────────────────────

    def _do_save(self):
        full_text = " ".join(self._full_text).strip()
        if not full_text:
            messagebox.showwarning("Nothing to save",
                                   "No transcription text yet.", parent=self.root)
            return

        # Determine path
        if self.output_path:
            save_path = Path(self.output_path)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = DEFAULT_OUTPUT / f"transcript_{ts}.txt"

        # Ask save permission (GUID shown inside)
        if not self._ask_save_permission(full_text, save_path):
            return

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(full_text, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return

        word_count = len(full_text.split())
        self.result = {
            "status":     "ok",
            "session_id": self.session_id,
            "file":       str(save_path),
            "word_count": word_count,
            "preview":    full_text[:300],
            "markdown":   (
                f"## Transcription saved\n\n"
                f"- **File**: `{save_path}`\n"
                f"- **Words**: {word_count}\n"
                f"- **Session**: `{self.session_id}`\n\n"
                f"---\n\n{full_text[:500]}"
                + ("…" if len(full_text) > 500 else "")
            ),
        }
        self._set_status(f"💾  Saved → {save_path.name}", GREEN)
        messagebox.showinfo("Saved",
                            f"Transcription saved!\n\n{save_path}",
                            parent=self.root)
        self.root.destroy()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = FG):
        self._status_lbl.config(text=text, fg=color)

    def _fatal(self, msg: str):
        messagebox.showerror("Fatal error", msg, parent=self.root)
        self.result = {"status": "error", "message": msg}
        self.root.destroy()

    def _on_close(self):
        self.recording = False
        if not self.result:
            self.result = {"status": "cancelled", "message": "Window closed by user."}
        self.root.destroy()


# ── tiny widget helpers ───────────────────────────────────────────────────────

def _frame(parent, **kw) -> tk.Frame:
    return tk.Frame(parent, **kw)

def _btn(parent, text: str, cmd, bg: str, fg: str, width: int = 0) -> tk.Button:
    b = tk.Button(parent, text=text, command=cmd,
                  bg=bg, fg=fg,
                  font=("Helvetica", 11, "bold"),
                  relief="flat", cursor="hand2",
                  activebackground=bg, activeforeground=fg,
                  padx=12, pady=6)
    if width:
        b.config(width=width)
    return b


# ═══════════════════════════════════════════════════════════════════════════════
#  Soul Engine App wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class TranscriptionApp(soul_engine_app):
    """soul_engine_app wrapper for the transcription GUI."""

    def __init__(self):
        super().__init__(app_name="SOUL TRANSCRIPTION")
        self._commands = {
            "transcribe": self._handle_transcribe,
            "record":     self._handle_transcribe,
            "start":      self._handle_transcribe,
        }

    # ── command handlers ──────────────────────────────────────────────────────

    def _handle_transcribe(self, args: list) -> dict:
        """
        Args (optional):
          transcribe                      → auto-named file in ~/transcriptions/
          transcribe /path/to/output.txt  → explicit path
        """
        output_path: Path | None = None
        for arg in args:
            if not arg.startswith("--"):
                output_path = Path(arg).expanduser().resolve()
                break

        gui = TranscriptionGUI(output_path=output_path)
        return gui.run()

    # ── entry point ───────────────────────────────────────────────────────────

    async def process_command(self, se_interface, args):
        if not args:
            cmd, cmd_args = "transcribe", []
        else:
            cmd = args[0].lower()
            cmd_args = args[1:]

        handler = self._commands.get(cmd)
        if handler:
            result = handler(cmd_args)
        else:
            # Bare path or unknown → treat as transcribe with possible path
            result = self._handle_transcribe(args)

        se_interface.send_message(json.dumps(result, ensure_ascii=False))


# ── standalone entry ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = TranscriptionApp()
    app.run_one_shot()