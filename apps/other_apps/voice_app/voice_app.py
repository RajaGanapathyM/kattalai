"""
Soul Voice App  —  REPL  (clean rewrite)
─────────────────────────────────────────
Explicit, simple listen / speak lifecycle.

Soul Engine Commands
────────────────────
  listen             → show GUI, start recording immediately
  speak <text>       → speak text aloud via TTS  (also: say / tts / read / aloud)

Soul Engine receives (unsolicited, sent by this app)
────────────────────────────────────────────────────
  {"status":"ok",     "action":"listen", "transcript":"…", "model":"base"}
  {"status":"closed", "action":"listen", "transcript":"",  "model":"base"}

Lifecycle
─────────
  1.  process_command("listen")   → signals main thread → GUI opens → recording starts
                                    returns {"status":"listening"} immediately
  2.  User speaks + silence       → transcript sent → Listen button enabled
  3.  User presses Listen button  → new recording starts → transcript sent → repeat
  4.  User closes window          → {"status":"closed"} sent → gui = None
  5.  process_command("listen")   → GUI rebuilt → cycle repeats

  process_command("speak …")      → TTS (works any time, concurrent-safe)

Dependencies
────────────
  pip install pyttsx3 faster-whisper sounddevice numpy
  Linux: sudo apt install libportaudio2
"""

from __future__ import annotations

import json
import queue
import sys
import asyncio
import threading
import uuid
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import scrolledtext

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
    import pyttsx3
    PYTTSX3_OK = True
except ImportError:
    PYTTSX3_OK = False

try:
    import sounddevice as sd
    import numpy as np
    SD_OK = True
except ImportError:
    SD_OK = False

try:
    from faster_whisper import WhisperModel
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False

# ── tunables ───────────────────────────────────────────────────────────────────
WHISPER_MODEL   = "base"
SAMPLE_RATE     = 16_000
CHUNK_FRAMES    = 1_600         # 0.1 s per chunk

# Speech detection — lower = more sensitive.
# Print RMS values are logged to stdout; tune SPEECH_RMS to sit just above
# your ambient noise floor (typically 0.002–0.010 for a laptop mic).
SPEECH_RMS      = 0.01         # RMS above this → speech detected
SILENCE_SEC     = 1.8           # seconds of silence after speech → stop
MAX_RECORD_S    = 60

TTS_RATE        = 170
TTS_VOLUME      = 1.0
TTS_VOICE_INDEX = 2         # 0 = default, try 1, 2, etc. for different voices

# ── palette ────────────────────────────────────────────────────────────────────
BG        = "#0b0f14"
PANEL     = "#131920"
BORDER    = "#1e2a35"
GREEN     = "#4ade80"
GREEN_DIM = "#14532d"
RED       = "#f87171"
AMBER     = "#fbbf24"
BLUE      = "#60a5fa"
BLUE_DIM  = "#1e3a5f"
TEAL      = "#2dd4bf"
FG        = "#e2e8f0"
FG_DIM    = "#64748b"
MONO      = ("Courier New", 9)
SANS      = ("Helvetica", 11)

# ── Whisper singleton ──────────────────────────────────────────────────────────
_whisper      = None
_whisper_lock = threading.Lock()
_MODEL_DIR    = Path(__file__).resolve().parent / "models"


def _list_tts_voices() -> None:
    """Print available TTS voices for reference."""
    if not PYTTSX3_OK:
        print("[TTS-VOICES] pyttsx3 not available", flush=True)
        return
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        print("[TTS-VOICES] Available voices:", flush=True)
        for i, voice in enumerate(voices):
            print(f"  [{i}] {voice.name} (ID: {voice.id})", flush=True)
        print(f"[TTS-VOICES] Change voice by setting TTS_VOICE_INDEX = 0..{len(voices)-1}", flush=True)
    except Exception as e:
        print(f"[TTS-VOICES] ✗ Failed to list voices: {e}", flush=True)


def _get_whisper() -> "WhisperModel":
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            print(f"[WHISPER] ✓ Loading Whisper model '{WHISPER_MODEL}'…", flush=True)
            if not WHISPER_OK:
                raise RuntimeError("faster_whisper not available")
            try:
                _MODEL_DIR.mkdir(parents=True, exist_ok=True)
                print(f"[WHISPER] ✓ Model directory ready: {_MODEL_DIR}", flush=True)
                _whisper = WhisperModel(
                    WHISPER_MODEL, device="cpu",
                    compute_type="int8", download_root=str(_MODEL_DIR),
                )
                print(f"[WHISPER] ✓ Whisper model loaded successfully", flush=True)
            except Exception as e:
                print(f"[WHISPER] ✗ Failed to load Whisper: {e}", flush=True)
                import traceback
                traceback.print_exc()
                raise
        else:
            print(f"[WHISPER] ✓ Using cached Whisper model", flush=True)
    return _whisper


# ══════════════════════════════════════════════════════════════════════════════
#  Audio helpers
# ══════════════════════════════════════════════════════════════════════════════

def _speak_blocking(text: str) -> None:
    """Synchronous TTS – run in a thread."""
    try:
        if not PYTTSX3_OK:
            raise RuntimeError("pyttsx3 not available")
        print(f"[TTS-EXEC] ✓ Initializing pyttsx3…", flush=True)
        engine = pyttsx3.init()
        print(f"[TTS-EXEC] ✓ Engine initialized, setting properties…", flush=True)
        engine.setProperty("rate",   TTS_RATE)
        engine.setProperty("volume", TTS_VOLUME)
        
        # Set voice
        voices = engine.getProperty("voices")
        if TTS_VOICE_INDEX < len(voices):
            engine.setProperty("voice", voices[TTS_VOICE_INDEX].id)
            print(f"[TTS-EXEC] ✓ Voice set to: {voices[TTS_VOICE_INDEX].name}", flush=True)
        else:
            print(f"[TTS-EXEC] ⚠  Voice index {TTS_VOICE_INDEX} out of range, using default", flush=True)
        
        print(f"[TTS-EXEC] ✓ Speaking: {text[:60]!r}…", flush=True)
        engine.say(text)
        print(f"[TTS-EXEC] ✓ Waiting for TTS to complete…", flush=True)
        engine.runAndWait()
        print(f"[TTS-EXEC] ✓ TTS complete", flush=True)
        engine.stop()
    except Exception as e:
        print(f"[TTS-EXEC] ✗ TTS failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


def _record_utterance(
    on_status,                  # callable(text, colour)
    stop_ev: threading.Event,   # set to abort
) -> "np.ndarray | None":
    """
    Record from mic until SILENCE_SEC of silence after speech, or stop_ev fires.
    Returns float32 array or None if aborted / no speech detected.

    RMS values are printed to stdout — tune SPEECH_RMS to sit just above
    your ambient noise floor (watch the [REC] rms=… lines while quiet).
    """
    print(f"[REC] ✓ _record_utterance started, checking deps…", flush=True)
    if not SD_OK:
        msg = "sounddevice/numpy not available"
        print(f"[REC] ✗ {msg}", flush=True)
        on_status(f"❌  {msg}", RED)
        return None

    import time

    chunks: list  = []
    spoken        = False
    last_speech_t = None
    start_t       = time.monotonic()

    print(f"[REC] ✓ Starting audio stream…", flush=True)
    on_status("🎙  Listening…  (watching for speech)", GREEN)

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1,
        dtype="float32", blocksize=CHUNK_FRAMES,
    ) as stream:
        while not stop_ev.is_set():
            elapsed = time.monotonic() - start_t
            if elapsed > MAX_RECORD_S:
                print(f"[REC] Max duration {MAX_RECORD_S}s reached", flush=True)
                break

            data, _ = stream.read(CHUNK_FRAMES)
            rms = float(np.sqrt(np.mean(data ** 2)))

            # Log every chunk so you can tune SPEECH_RMS to your mic
            print(f"[REC] rms={rms:.5f}  spoken={spoken}  t={elapsed:.1f}s",
                  flush=True)

            if rms >= SPEECH_RMS:
                if not spoken:
                    print("[REC] Speech started", flush=True)
                    on_status("🔴  Recording speech…", RED)
                spoken        = True
                last_speech_t = time.monotonic()
                chunks.append(data.copy())
                bar = "█" * min(24, int(rms * 400))
                on_status(f"🔴  {elapsed:.1f}s  |{bar:<24}|", RED)
            else:
                if spoken:
                    chunks.append(data.copy())   # keep trailing silence for Whisper
                    silence_dur = time.monotonic() - last_speech_t
                    remaining   = max(0.0, SILENCE_SEC - silence_dur)
                    on_status(
                        f"⏸  silence {silence_dur:.1f}s / {SILENCE_SEC:.1f}s"
                        f"  (ends in {remaining:.1f}s)", AMBER)
                    if silence_dur >= SILENCE_SEC:
                        print("[REC] Silence threshold reached — stopping", flush=True)
                        break
                else:
                    on_status(
                        f"🎙  Waiting…  rms={rms:.4f}  threshold={SPEECH_RMS}",
                        GREEN)

    if stop_ev.is_set():
        print("[REC] Aborted", flush=True)
        return None

    if not spoken or not chunks:
        print("[REC] No speech detected", flush=True)
        return None

    return np.concatenate(chunks, axis=0).flatten()


def _transcribe(audio: "np.ndarray", on_status) -> str:
    print(f"[TRANSCRIBE] ✓ Starting transcription, audio size: {len(audio) if audio is not None else 'None'}", flush=True)
    on_status("⚙️  Transcribing…", AMBER)
    try:
        print(f"[TRANSCRIBE] ✓ Loading Whisper model…", flush=True)
        model = _get_whisper()
        print(f"[TRANSCRIBE] ✓ Model loaded, transcribing…", flush=True)
        segs, _ = model.transcribe(audio, beam_size=5, language=None, vad_filter=True)
        print(f"[TRANSCRIBE] ✓ Transcription segments received, assembling…", flush=True)
        result = " ".join(s.text.strip() for s in segs).strip()
        print(f"[TRANSCRIBE] ✓ Transcription complete: {result[:80]!r}", flush=True)
        return result
    except Exception as e:
        print(f"[TRANSCRIBE] ✗ Transcription failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════

class VoiceGUI:
    """
    One GUI window = one listen session.

    External interface
    ──────────────────
    • build_and_run()        – build window, start auto-recording, enter mainloop
    • speak_queue            – put text here to queue a TTS utterance
    • tts_done_event         – set when TTS finishes (callers may wait on it)

    Callbacks (called on main / Tk thread)
    ──────────────────────────────────────
    • on_transcript(text)    – fired after each successful recording
    • on_close()             – fired when user closes window
    • on_speak_done()        – fired after TTS finishes (used to open listen dialog)
    """

    def __init__(
        self,
        on_transcript,          # callable(str)
        on_close,               # callable()
        speak_queue: queue.Queue,
        on_speak_done=None,     # callable() - fired after TTS completes
    ):
        self._on_transcript = on_transcript
        self._on_close      = on_close
        self._speak_q       = speak_queue
        self._on_speak_done_cb = on_speak_done

        self.tts_done_event  = threading.Event()
        self.tts_done_event.set()          # starts as "done"

        self._stop_rec_ev   = threading.Event()   # set → abort active recording
        self._recording     = False
        self._speaking      = False
        self._status_q      = queue.Queue()        # thread-safe status updates

        self.session_id = str(uuid.uuid4())
        self.root       = None

    # ──────────────────────────────────────────────────────────────────────────
    #  Build + run
    # ──────────────────────────────────────────────────────────────────────────

    def build_and_run(self):
        """Build window, show ready state, enter Tk mainloop (blocks)."""
        try:
            print("[GUI] Starting build_and_run()", flush=True)
            self._build()
            print("[GUI] build() completed", flush=True)
            self._check_deps()
            print("[GUI] _check_deps() completed", flush=True)
            self._poll_speak_queue()
            self._poll_status_queue()
            print("[GUI] Entering mainloop…", flush=True)
            self.root.mainloop()
            print("[GUI] Exited mainloop", flush=True)
        except Exception as e:
            import traceback
            print(f"[GUI] ✗ build_and_run() failed: {e}", flush=True)
            traceback.print_exc()
            raise

    def _build(self):
        try:
            self.root = tk.Tk()
            self.root.title("Soul Voice")
            self.root.configure(bg=BG)
            self.root.resizable(False, False)
            self.root.protocol("WM_DELETE_WINDOW", self._handle_close)
            self.root.geometry("540x650")
            print("[GUI] ✓ Tk window created successfully", flush=True)
        except Exception as e:
            print(f"[GUI] ✗ Failed to create Tk window: {e}", flush=True)
            raise

        # header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(hdr, text="◉  SOUL VOICE",
                 font=("Helvetica", 15, "bold"), bg=BG, fg=TEAL).pack(side="left")
        tk.Label(hdr, text=self.session_id[:12],
                 font=MONO, bg=BG, fg=FG_DIM).pack(side="right")

        # status
        self._status_lbl = tk.Label(
            self.root, text="🎙  Press Listen to begin",
            font=SANS, bg=BG, fg=GREEN, anchor="w")
        self._status_lbl.pack(fill="x", padx=20, pady=(0, 6))

        # conversation log
        lf = tk.Frame(self.root, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=20, pady=(0, 6))

        lh = tk.Frame(lf, bg=PANEL)
        lh.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(lh, text="CONVERSATION",
                 font=MONO, bg=PANEL, fg=FG_DIM).pack(side="left")
        tk.Button(lh, text="clear", font=MONO,
                  bg=PANEL, fg=FG_DIM, relief="flat", cursor="hand2",
                  command=self._clear_log).pack(side="right")

        self._log = scrolledtext.ScrolledText(
            lf, wrap=tk.WORD, font=("Helvetica", 10),
            bg=PANEL, fg=FG, relief="flat",
            state="disabled", padx=8, pady=6,
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=(2, 8))
        self._log.tag_config("agent",  foreground=BLUE)
        self._log.tag_config("user",   foreground=GREEN)
        self._log.tag_config("system", foreground=FG_DIM)
        self._log.tag_config("error",  foreground=RED)

        # listen button
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(fill="x", padx=20, pady=(0, 16), expand=False)

        self._listen_btn = tk.Button(
            btn_frame,
            text="🎙  Listen",
            font=("Helvetica", 12, "bold"),
            bg=GREEN_DIM, fg=GREEN,
            activebackground=GREEN, activeforeground=BG,
            relief="flat", cursor="hand2",
            padx=20, pady=8,
            state="normal",
            command=self._on_listen_pressed,
        )
        self._listen_btn.pack(fill="x", expand=True)

    def _check_deps(self):
        missing = []
        if not PYTTSX3_OK:  missing.append("pyttsx3")
        if not SD_OK:       missing.append("sounddevice numpy")
        if not WHISPER_OK:  missing.append("faster-whisper")
        if missing:
            msg = "Missing deps: pip install " + " ".join(missing)
            self._set_status("❌  " + msg, RED)
            self._set_btn("disabled")
            self._log_add(msg + "\n", "error")
        else:
            self._log_add("Ready. Press Listen to begin.\n", "system")
            _list_tts_voices()
            self._set_status("🎙  Press Listen to begin", GREEN)

    # ──────────────────────────────────────────────────────────────────────────
    #  Recording lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def _start_recording(self):
        """Start one recording session in a background thread."""
        print("[REC] _start_recording() called", flush=True)
        if not (SD_OK and WHISPER_OK):
            msg = "Missing audio dependencies (sounddevice/numpy/faster-whisper)"
            print(f"[REC] ✗ {msg}", flush=True)
            self._set_status(f"❌  {msg}", RED)
            self._set_btn("idle")
            return

        self._recording = True
        self._stop_rec_ev.clear()
        # Update status and button immediately on main thread — do NOT rely on
        # the background thread calling back, which can be dropped before mainloop.
        self._set_status("🎙  Listening…  speak now", GREEN)
        self._log_add("🎙  Listening…\n", "system")
        self._set_btn("recording")
        print("[REC] ✓ Recording state set, starting worker thread…", flush=True)

        threading.Thread(
            target=self._record_worker, daemon=True, name="record-worker"
        ).start()
        print("[REC] ✓ Worker thread started", flush=True)

    def _record_worker(self):
        """Background thread: record → transcribe → dispatch to main thread."""
        try:
            print("[REC-WORKER] ✓ Recording worker started", flush=True)
            audio = _record_utterance(
                on_status=self._status_from_thread,
                stop_ev=self._stop_rec_ev,
            )
            print(f"[REC-WORKER] ✓ Recording completed, audio size: {len(audio) if audio is not None else 'None'}", flush=True)
        except Exception as exc:
            print(f"[REC-WORKER] ✗ Recording failed: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            self._after(lambda: self._on_record_error(str(exc)))
            return

        if audio is None:
            print("[REC-WORKER] ⚠  No audio recorded (aborted or no speech)", flush=True)
            self._after(self._on_record_aborted)
            return

        try:
            print("[REC-WORKER] ✓ Starting transcription…", flush=True)
            text = _transcribe(audio, self._status_from_thread)
            print(f"[REC-WORKER] ✓ Transcription completed: {text[:80]!r}", flush=True)
        except Exception as exc:
            print(f"[REC-WORKER] ✗ Transcription failed: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            self._after(lambda: self._on_record_error(str(exc)))
            return

        print("[REC-WORKER] ✓ Dispatching transcript to main thread", flush=True)
        self._after(lambda: self._on_record_done(text))

    # called on main thread ────────────────────────────────────────────────────

    def _on_record_done(self, text: str):
        self._recording = False
        if text:
            self._log_add(f"🎤  {text}\n", "user")
            self._set_status("📤  Transcript sent", TEAL)
            self._autosave(text)
            self._on_transcript(text)          # → VoiceApp callback
        else:
            self._set_status("🔇  Nothing detected — press Listen to retry", FG_DIM)
        self._set_btn("idle")                  # ← enable Listen button

    def _on_record_aborted(self):
        self._recording = False
        self._set_status("⏹  Stopped", FG_DIM)
        # Don't re-enable if we stopped because TTS is about to speak
        if not self._speaking:
            self._set_btn("idle")

    def _on_record_error(self, msg: str):
        self._recording = False
        self._set_status(f"❌  {msg[:80]}", RED)
        self._log_add(f"Error: {msg}\n", "error")
        self._set_btn("idle")

    def _on_listen_pressed(self):
        """User pressed the Listen button."""
        self._start_recording()

    # ──────────────────────────────────────────────────────────────────────────
    #  TTS
    # ──────────────────────────────────────────────────────────────────────────

    def _poll_speak_queue(self):
        """Drain one item from speak_queue per poll cycle."""
        if self.root is None:
            return
        try:
            text = self._speak_q.get_nowait()
            if not self._speaking:
                self._do_speak(text)
            else:
                # Put it back; we'll catch it next poll
                self._speak_q.put(text)
        except queue.Empty:
            pass
        if self.root:
            self.root.after(100, self._poll_speak_queue)

    def _do_speak(self, text: str):
        print(f"[TTS] ✓ _do_speak called with text: {text[:60]!r}", flush=True)
        self._speaking = True
        self.tts_done_event.clear()

        # Abort any active recording so TTS isn't drowned out
        if self._recording:
            print("[TTS] ✓ Aborting active recording for TTS…", flush=True)
            self._stop_rec_ev.set()

        self._set_status("🔊  Speaking…", BLUE)
        self._log_add(f"🤖  {text}\n", "agent")
        self._set_btn("speaking")
        print("[TTS] ✓ UI updated, starting TTS worker thread…", flush=True)

        def _worker():
            try:
                print("[TTS-WORKER] ✓ TTS worker started", flush=True)
                _speak_blocking(text)
                print("[TTS-WORKER] ✓ TTS completed successfully", flush=True)
            except Exception as exc:
                print(f"[TTS-WORKER] ✗ TTS failed: {exc}", flush=True)
                import traceback
                traceback.print_exc()
                self._after(lambda: self._set_status(
                    f"❌  TTS error: {str(exc)[:60]}", RED))
            finally:
                print("[TTS-WORKER] ✓ Calling _on_speak_done", flush=True)
                self._after(self._on_speak_done)

        threading.Thread(target=_worker, daemon=True, name="tts-worker").start()
        print("[TTS] ✓ TTS worker thread started", flush=True)

    def _on_speak_done(self):
        """Called on main thread after TTS finishes."""
        self._speaking = False
        self.tts_done_event.set()
        self._stop_rec_ev.clear()
        # Re-enable Listen button so user can respond
        self._set_btn("idle")
        self._set_status("🎙  Press Listen to respond", GREEN)
        # Trigger callback to open listen dialog if needed
        if self._on_speak_done_cb:
            print("[TTS] ✓ Calling on_speak_done callback to open listen dialog", flush=True)
            self._on_speak_done_cb()

    # ──────────────────────────────────────────────────────────────────────────
    #  Close
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_close(self):
        """User closed the window."""
        print("[GUI] Window closed", flush=True)
        self._stop_rec_ev.set()
        try:
            self.root.destroy()
        except Exception:
            pass
        self.root = None
        self._on_close()          # → VoiceApp callback

    # ──────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _after(self, fn):
        if self.root:
            try:
                self.root.after(0, fn)
            except Exception:
                pass

    def _status_from_thread(self, text: str, colour: str):
        """Called from background threads — push to queue, polled on main thread."""
        self._status_q.put((text, colour))

    def _poll_status_queue(self):
        """Drain status updates queued by background threads. Runs on main thread."""
        try:
            while True:
                text, colour = self._status_q.get_nowait()
                self._set_status(text, colour)
        except queue.Empty:
            pass
        if self.root:
            self.root.after(80, self._poll_status_queue)

    def _set_status(self, text: str, colour: str = FG):
        if self.root and hasattr(self, "_status_lbl"):
            self._status_lbl.config(text=text, fg=colour)

    def _set_btn(self, state: str):
        """state: 'idle' | 'recording' | 'speaking' | 'disabled'"""
        if not (self.root and hasattr(self, "_listen_btn")):
            return
        if state == "idle":
            self._listen_btn.config(
                state="normal", bg=GREEN_DIM, fg=GREEN,
                text="🎙  Listen",
            )
        elif state == "recording":
            self._listen_btn.config(
                state="disabled", bg=BLUE_DIM, fg=FG_DIM,
                text="⏳  Recording…",
            )
        elif state == "speaking":
            self._listen_btn.config(
                state="disabled", bg=BLUE_DIM, fg=FG_DIM,
                text="🔊  Speaking…",
            )
        elif state == "disabled":
            self._listen_btn.config(
                state="disabled", bg=BORDER, fg=FG_DIM,
                text="🎙  Listen",
            )

    def _log_add(self, text: str, tag: str = ""):
        if not (self.root and hasattr(self, "_log")):
            return
        self._log.config(state="normal")
        self._log.insert(tk.END, text, tag)
        self._log.see(tk.END)
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", tk.END)
        self._log.config(state="disabled")

    def _autosave(self, text: str):
        folder = Path.home() / "voice_results"
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"voice_{ts}.txt").write_text(text, encoding="utf-8")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  VoiceApp  —  Soul Engine REPL
# ══════════════════════════════════════════════════════════════════════════════

class VoiceApp(soul_engine_app):
    """
    Thread layout
    ─────────────
      main thread   →  Tk GUI main loop (blocks per session)
      se-repl       →  soul engine REPL (reads stdin / sends stdout)

    process_command is called on the se-repl thread.
      • speak/say   →  put text in speak_queue, wait for TTS done
      • listen      →  signal main thread to open GUI, return "listening" ack
                       subsequent transcripts fired via _on_transcript callback
    """

    def __init__(self):
        print("[APP] ✓ VoiceApp.__init__() called", flush=True)
        try:
            super().__init__(app_name="SOUL VOICE")
            print("[APP] ✓ Parent soul_engine_app initialized", flush=True)
        except Exception as e:
            print(f"[APP] ✗ Parent initialization failed: {e}", flush=True)
            raise

        self._speak_queue   = queue.Queue()
        self._gui: VoiceGUI | None = None
        self._gui_lock      = threading.Lock()
        self._se_interface  = None          # saved so callbacks can send messages
        self._iface_lock    = threading.Lock()

        # signalled by process_command("listen") to open a new GUI on main thread
        self._open_gui_ev   = threading.Event()
        print("[APP] ✓ VoiceApp state initialized", flush=True)

    # ── command handler (se-repl thread) ──────────────────────────────────────

    async def process_command(self, se_interface, args):
        try:
            with self._iface_lock:
                self._se_interface = se_interface

            cmd  = (args[0].lower() if args else "")
            text = " ".join(args[1:]).strip() if len(args) > 1 else ""

            print(f"[APP] ✓ process_command called: cmd={cmd!r} text={text[:60]!r}", flush=True)

            # ── speak ──────────────────────────────────────────────────────────────
            if cmd in ("speak", "say", "tts", "read", "aloud"):
                if not text:
                    msg = "No text to speak"
                    print(f"[APP] ✗ {msg}", flush=True)
                    se_interface.send_message(json.dumps(
                        {"status": "error", "message": msg}))
                    return

                print(f"[APP] ✓ TTS: {text[:60]!r}", flush=True)
                with self._gui_lock:
                    gui = self._gui

                if gui:
                    print("[APP] GUI exists, queueing TTS…", flush=True)
                    self._speak_queue.put(text)
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: gui.tts_done_event.wait(timeout=120))
                    print("[APP] ✓ TTS completed", flush=True)
                else:
                    # No GUI open — speak via background thread anyway
                    print("[APP] No GUI, speaking directly…", flush=True)
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: _speak_blocking(text))
                    print("[APP] ✓ Direct TTS completed, opening listen GUI…", flush=True)
                    # Signal GUI to open after TTS completes
                    self._open_gui_ev.set()
                return

            # ── listen ─────────────────────────────────────────────────────────────
            if cmd == "listen" or not text:
                print("[APP] ✓ Listen command received", flush=True)
                with self._gui_lock:
                    already_open = self._gui is not None

                if already_open:
                    print("[APP] ⚠  GUI already open — ignoring duplicate listen", flush=True)
                    se_interface.send_message(json.dumps(
                        {"status": "listening", "action": "listen",
                         "note": "GUI already open"}))
                else:
                    print("[APP] ✓ Requesting GUI open…", flush=True)
                    self._open_gui_ev.set()
                    print("[APP] ✓ GUI event signaled, sending listening ack…", flush=True)
                    se_interface.send_message(json.dumps(
                        {"status": "listening", "action": "listen"}))
                    print("[APP] ✓ Listening ack sent", flush=True)
                return

            # ── unknown ────────────────────────────────────────────────────────────
            msg = f"Unknown command: {cmd}"
            print(f"[APP] ✗ {msg}", flush=True)
            se_interface.send_message(json.dumps(
                {"status": "error", "message": msg}))
        except Exception as e:
            import traceback
            print(f"[APP] ✗ process_command failed: {e}", flush=True)
            traceback.print_exc()
            try:
                se_interface.send_message(json.dumps(
                    {"status": "error", "message": f"Command failed: {str(e)[:100]}"}))
            except Exception as send_err:
                print(f"[APP] ✗ Failed to send error: {send_err}", flush=True)

    # ── GUI callbacks (main thread) ────────────────────────────────────────────

    def _on_transcript(self, transcript: str):
        """Fired by GUI on main thread when a recording completes."""
        try:
            print(f"[CALLBACK] ✓ _on_transcript called: {transcript[:80]!r}", flush=True)
            with self._iface_lock:
                iface = self._se_interface
            if iface and transcript:
                payload = json.dumps({
                    "status":     "ok",
                    "action":     "listen",
                    "transcript": transcript,
                    "model":      WHISPER_MODEL,
                }, ensure_ascii=False)
                print(f"[CALLBACK] ✓ Sending transcript to SE interface with invoke…", flush=True)
                iface.send_and_invoke(payload)
                print(f"[CALLBACK] ✓ Transcript sent and invoke triggered", flush=True)
            else:
                if not iface:
                    print(f"[CALLBACK] ⚠  No SE interface available", flush=True)
                if not transcript:
                    print(f"[CALLBACK] ⚠  Empty transcript", flush=True)
        except Exception as e:
            print(f"[CALLBACK] ✗ _on_transcript failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _on_gui_close(self):
        """Fired by GUI on main thread when window is closed."""
        try:
            print(f"[CALLBACK] ✓ _on_gui_close called", flush=True)
            with self._gui_lock:
                self._gui = None
            print(f"[CALLBACK] ✓ GUI reference cleared", flush=True)

            with self._iface_lock:
                iface = self._se_interface

            if iface:
                payload = json.dumps({
                    "status":     "closed",
                    "action":     "listen",
                    "transcript": "",
                    "model":      WHISPER_MODEL,
                }, ensure_ascii=False)
                print(f"[CALLBACK] ✓ Sending close message to SE interface…", flush=True)
                iface.send_message(payload)
                print(f"[CALLBACK] ✓ Close message sent", flush=True)
            else:
                print(f"[CALLBACK] ⚠  No SE interface to notify", flush=True)
        except Exception as e:
            print(f"[CALLBACK] ✗ _on_gui_close failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _on_tts_done(self):
        """Fired by GUI on main thread when TTS finishes. Open listen dialog if not already open."""
        try:
            print(f"[CALLBACK] ✓ _on_tts_done called", flush=True)
            with self._gui_lock:
                already_open = self._gui is not None
            
            if not already_open:
                print("[CALLBACK] ✓ Listen dialog not open, opening it…", flush=True)
                self._open_gui_ev.set()
            else:
                print("[CALLBACK] ✓ Listen dialog already open, keeping it visible", flush=True)
        except Exception as e:
            print(f"[CALLBACK] ✗ _on_tts_done failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

    # ── main thread GUI loop ───────────────────────────────────────────────────

    def _gui_main_loop(self):
        """
        Runs on the main thread forever.
        Waits for listen signals, builds GUI, blocks on mainloop, repeats.
        """
        while True:
            try:
                print("[MAIN] Waiting for listen signal…", flush=True)
                self._open_gui_ev.wait()      # block until process_command("listen")
                self._open_gui_ev.clear()

                print("[MAIN] ✓ Building VoiceGUI…", flush=True)
                gui = VoiceGUI(
                    on_transcript=self._on_transcript,
                    on_close=self._on_gui_close,
                    speak_queue=self._speak_queue,
                    on_speak_done=self._on_tts_done,
                )
                with self._gui_lock:
                    self._gui = gui

                print("[MAIN] ✓ GUI object created, starting build_and_run()…", flush=True)
                gui.build_and_run()           # blocks until window is closed
                print("[MAIN] ✓ GUI mainloop exited", flush=True)
                # _on_gui_close already cleared self._gui; loop waits for next listen
            except Exception as e:
                import traceback
                print(f"[MAIN] ✗ GUI loop error: {e}", flush=True)
                traceback.print_exc()
                with self._gui_lock:
                    self._gui = None
                # Report error to Soul Engine
                with self._iface_lock:
                    iface = self._se_interface
                if iface:
                    try:
                        iface.send_message(json.dumps({
                            "status": "error",
                            "action": "listen",
                            "message": f"GUI error: {str(e)[:100]}"
                        }))
                    except Exception as send_err:
                        print(f"[MAIN] ✗ Failed to send error message: {send_err}", flush=True)

    # ── entry point ────────────────────────────────────────────────────────────

    def run(self):
        print("[APP] ✓ VoiceApp.run() called", flush=True)
        # REPL on background thread (non-daemon so process stays alive)
        print("[APP] ✓ Starting REPL worker thread…", flush=True)
        threading.Thread(
            target=self._repl_worker, daemon=False, name="se-repl"
        ).start()
        print("[APP] ✓ REPL worker thread started", flush=True)

        # GUI on main thread (required by Tk)
        print("[APP] ✓ Starting GUI main loop on main thread…", flush=True)
        self._gui_main_loop()

    def _repl_worker(self):
        print("[APP] ✓ REPL worker started", flush=True)
        try:
            print("[APP] ✓ Attempting to run REPL…", flush=True)
            self.run_repl()
            print("[APP] ✓ REPL completed normally", flush=True)
        except AttributeError as e:
            print(f"[APP] ⚠  run_repl not found, trying run_one_shot: {e}", flush=True)
            try:
                self.run_one_shot()
                print("[APP] ✓ run_one_shot completed normally", flush=True)
            except AttributeError as exc:
                print(f"[APP] ✗ No run method found: {exc}", flush=True)
            except Exception as exc:
                import traceback
                print(f"[APP] ✗ run_one_shot crashed: {exc}", flush=True)
                traceback.print_exc()
        except Exception as exc:
            import traceback
            print(f"[APP] ✗ REPL crashed: {exc}", flush=True)
            traceback.print_exc()


# ── entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    VoiceApp().run()