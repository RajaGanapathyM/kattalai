from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional
import logging
import json
import subprocess
from pathlib import Path
import urllib.request
import zipfile
import shutil
import subprocess
import sys
from rich.markup import escape

GITHUB_REPO = "RajaGanapathyM/kattalai"
BRANCH = "main"
# Setup a basic logger
logging.basicConfig(filename="newdebug.log", level=logging.INFO)
# ── SoulEngine import (Windows DLL fix + graceful fallback) ─────────────────
SE_AVAILABLE = False
GLOBAL_SE_RUNTIME=None
try:
    import torch
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(_torch_lib):
        os.add_dll_directory(_torch_lib)
    from soulengine import PyRuntime
    SE_AVAILABLE = True
    
except Exception  as e:
    print(str(e))
    pass  # Falls through to DEMO mode automatically

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, RichLog, Select, Static, TextArea, Button, DirectoryTree
from textual.events import Key

# ─────────────────────────────────────────────────────────────
# Static data (used in demo mode + Space/Mind tabs seed)
# ─────────────────────────────────────────────────────────────

AGENTS=[]
se_bind="127.0.0.1:3077"
async def load_run_time():
    global AGENTS,GLOBAL_SE_RUNTIME
    GLOBAL_SE_RUNTIME=await PyRuntime.create(bind=se_bind)
    AGENTS = await GLOBAL_SE_RUNTIME.get_agent_list()
    print("Loaded Agents:",AGENTS)

APPS = [
    ("Gmail",  True),
    ("GCal",   True),
    ("Notion", False),
    ("GitHub", False),
    ("Linear", False),
    ("Slack",  False),
]

TABS = [("Chat","chat-pane"),
        ("Agent Thoughts","agent-pane"), 
        ("Logs","terminal-pane")]

# ─────────────────────────────────────────────────────────────
# Response block parser
# ─────────────────────────────────────────────────────────────
BLOCK_ICONS = {
    "thoughts":   ("◆", "thoughts"),
    "terminal":   ("$", "terminal"),
    "output":     ("*", "output_"),
    "validation": ("✓", "validation"),
    "followup_context": ("→", "followup"),
}

def parse_se_content(content: str) -> list[tuple[str, str]]:
    """Parse markdown code-fenced agent blocks like ```thoughts ... ```"""
    import re
    pattern = re.compile(
        r'```(thoughts|terminal|output|validation|followup_context)\s*\n(.*?)```',
        re.DOTALL
    )
    matches = pattern.findall(content)
    if matches:
        return [(kind.strip(), body.strip()) for kind, body in matches if body.strip()]
    return [("output", content.strip())]

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

CSS = """
$bg:     #0c0e12;
$surf:   #13161d;
$bord:   #1f2430;
$bord2:  #2a2f3d;
$text:   #c9d1e0;
$muted:  #4a5270;
$green:  #4ade80;
$blue:   #60a5fa;
$amber:  #f59e0b;
$purple: #e879f9;
$red:    #f87171;
$cyan:   #22d3ee;
$text-muted: #6b7280;
Screen { background: $bg; color: $text; layout: vertical; }

/* ── Top bar ── */
#topbar {
    layout: horizontal;
    width: 100%;
    height: 3;
    align: left middle;
}

#topbar-left {
    layout: horizontal;
    width: auto;
    align: left middle;
    padding-right: 1;
    height: 3;
}

#tabbar {
    layout: horizontal;
    width: 1fr;
    align: center middle;
    height: 3; background: $surf;
    border-bottom: tall $bord;
    padding: 0 2;
}

#topbar-right {
    layout: horizontal;
    width: auto;
    align: right middle;
    padding-left: 1;
    height: 3;   
}

#logo {
    color: $success;
    text-style: bold;
}

#logo-sub {
    color: $text-muted;
}

#clock {
    color: $text-muted;
    padding-left: 2;
}

/* ── Main shell ── */
#main { layout: horizontal; height: 1fr;width:1fr; }

/* ── Sidebar ── */
#sidebar {
    width: 20; background: $surf;
    border-right: tall $bord; padding: 1; layout: vertical;
}
.sbhead { color: $muted; text-style: bold; margin-bottom: 1; }

.agent-chip {
    height: 3; background: $bg; border: tall $bord2;
    padding: 0 1; margin-bottom: 1;
    layout: horizontal; align: center middle;
}
.agent-chip:hover  { background: #1a1f2e; }
.agent-chip.active { border: tall $green; background: #0d1a10; }
.chip-name { width: 1fr; padding-left: 1; }
.chip-dot  { width: 2; color: $muted; text-align: right; }
.agent-chip.active .chip-dot { color: $green; }
.chip-status { width: 2; color: $muted; text-align: right; }
.chip-status.live { color: $cyan; }

.divider { height: 1; background: $bord; margin: 1 0; }

.app-chip {
    height: 2; background: $bg; border: tall $bord2;
    padding: 0 1; margin-bottom: 1;
    layout: horizontal; align: center middle;
}
.app-chip.on { border: tall #1a3040; }
.app-name    { width: 1fr; padding-left: 1; color: $muted; }
.app-chip.on .app-name { color: $text; }
.app-dot     { width: 2; color: $muted; text-align: right; }
.app-chip.on .app-dot  { color: $green; }

/* ── Content column ── */
#content { width: 1fr; layout: vertical; height: 1fr; }

/* ── Tab bar ── */
.tab-btn {
    width: auto; height: 3; padding: 0 3;
    color: $text-muted; background: transparent; content-align: center middle;
}
.tab-btn:hover  { color: $text; background: #1a1f2e; }
.tab-btn.active { color: $green; text-style: bold; border-bottom: tall $green; }
.tab-sep { width: 1; color: $bord2; content-align: center middle; }
.tab-btn:focus {
    background: transparent;
}

/* ── Tab panes ── */
.tab-pane { width: 100%; height: 1fr; display: none; }
.tab-pane.show { display: block; }

/* ════ CHAT ════ */
#chat-pane-box { layout: vertical; }
#messages {
    width: 100%; height: 1fr; padding: 1 2;
    background: $bg; scrollbar-color: $bord2; scrollbar-size: 1 1;
}
.msg-row { width: 100%; margin-bottom: 2; layout: vertical; }
.usr-lbl { color: $muted; text-style: italic; }
.usr-txt {
    background: #151b2e; border-left: thick $blue;
    padding: 0 2; color: $text; margin-bottom: 1;
}
.agt-lbl { color: $muted; }
.block   { border-left: thick $muted; padding: 0 2; margin-bottom: 1; }
.thought { border-left: thick $muted; background: #111318; }
.exec    { border-left: thick $amber; background: #161200; }
.output_ { border-left: thick $green; background: #0d1a10; }
.blk-hdr { text-style: bold; }
.thought .blk-hdr { color: $muted; }
.exec    .blk-hdr { color: $amber; }
.output_ .blk-hdr { color: $green; }
.blk-body         { padding-left: 1; color: $text; }
.exec .blk-body   { color: $amber; }

.agent-strip {
    height: 1; background: $surf;
    border-top: tall $bord; border-bottom: tall $bord;
    padding: 0 2; layout: horizontal; align: center middle;
}
.strip-agent { width: auto; color: $green; text-style: bold; }
.strip-sep   { width: auto; color: $muted; padding: 0 1; }
.strip-hint  { width: auto; color: $muted; }

#thinking {
    height: 2; background: $surf; border-top: tall $bord2;
    padding: 0 2; layout: horizontal; align: center middle; display: none;
}
#thinking.show { display: block; }

#input-row {
    height: 5; background: $surf; border-top: tall $bord2; overflow: auto;
    padding: 0 2; layout: horizontal; align: center middle;
}
#prompt-icon { width: 5; color: $green; text-style: bold; }
#agent-select {
    width: 16;
    height: 3;
    border-left: tall $green;
    border-right: tall $bord2;
    border-top: tall $bord2;
    border-bottom: tall $bord2;
    background: #0d1a10;
    color: $green;
    margin-right: 1;
}
#agent-select:focus {
    border-left: tall $green;
    border-right: tall $green;
    border-top: tall $green;
    border-bottom: tall $green;
    background: #0f1f12;
}
#agent-select > SelectCurrent {
    background: transparent;
    color: $green;
    border: none;
    text-style: bold;
    padding: 0 1;
}
#agent-select > SelectCurrent:focus {
    background: transparent;
    border: none;
}
SelectOverlay {
    background: $surf;
    border: tall $green;
    color: $text;
}
SelectOverlay > .option-list--option-highlighted {
    background: #1a2f1a;
    color: $green;
}
SelectOverlay > .option-list--option {
    padding: 0 1;
    color: $text;
}
#user-input { width: 1fr; background: transparent; border: none; color: $text; padding: 0; }
#user-input:focus { border: none; background: transparent; }

/* ── Attach button ── */
#attach-btn {
    width: 7;
    height: 3;
    min-width: 3;
    background: #13161d;
    border: tall #2a2f3d;
    color: #4a5270;
    margin-left: 1;
    padding: 0;
    content-align: center middle;
}
#attach-btn:hover { border: tall #4ade80; color: #4ade80; background: #0d1a10; }
#attach-btn:focus { border: tall #4ade80; color: #4ade80; background: #0d1a10; }

/* ════ AGENT MIND ════ */
#agent-pane-box { layout: horizontal; padding: 1; background: $bg; }
.mind-col { width: 1fr; layout: vertical; margin-right: 1; height: 100%; }
.mind-col:last-child { margin-right: 0; }
.mind-head {
    height: 2; background: $surf; border: tall $bord;
    padding: 0 1; color: $text; text-style: bold;
    content-align: center middle; margin-bottom: 1;
}
.goal-card {
    background: $surf; border: tall $bord2; border-left: thick $muted;
    padding: 0 1; margin-bottom: 1; layout: vertical; height: 5;
}
.goal-primary { border-left: thick $green; background: #0d1a10; }
.goal-sub     { border-left: thick $blue;  background: #0d1222; }
.goal-tag           { color: $muted; }
.goal-primary .goal-tag { color: $green; text-style: bold; }
.goal-sub     .goal-tag { color: $blue; }
.goal-body { color: $text; padding-left: 1; }

#mind-history {
    width: 100%; height: 1fr; padding: 1 2;
    background: $bg; scrollbar-color: $bord2; scrollbar-size: 1 1;
}

.branch-card {
    background: $surf; border: tall $bord2; border-left: thick $muted;
    padding: 0 1; margin-bottom: 1; layout: vertical; height: 5;
}
.branch-card.chosen { border-left: thick $amber; background: #161200; }
.branch-tag               { color: $muted; }
.branch-card.chosen .branch-tag { color: $amber; text-style: bold; }
.branch-body { color: $text; padding-left: 1; }

.mem-card {
    background: $surf; border: tall $bord2;
    padding: 0 1; margin-bottom: 1;
    layout: horizontal; align: center middle; height: 3;
}
.mem-short { border-left: thick $green; }
.mem-long  { border-left: thick $purple; }
.mem-ctx   { border-left: thick $blue; }
.mem-epi   { border-left: thick $amber; }
.mem-text  { width: 1fr; color: $text; }
.mem-tag   { width: 11; color: $muted; text-align: right; }

/* ════ TERMINAL ════ */
#terminal-pane-box { layout: vertical; background: $bg; }
#term-log {
    width: 100%; height: 1fr; padding: 1 2;
    background: #080a0e; scrollbar-color: $bord2; scrollbar-size: 1 1;
}
#term-input-row {
    height: 3; background: $surf; border-top: tall $bord2;
    padding: 0 2; layout: horizontal; align: center middle;
}
#term-prompt { width: auto; color: $green; text-style: bold; padding-right: 1; }
#term-input  { width: 1fr; background: transparent; border: none; color: $text; padding: 0; }
#term-input:focus { border: none; background: transparent; }

/* ── Status bar ── */
#statusbar {
    height: 1; background: #080a0e;
    border-top: tall $bord; padding: 0 2;
    layout: horizontal; align: center middle;
}
.stat     { width: auto; color: $muted; padding-right: 2; }
.stat.ok  { color: $green; }
.stat.err { color: $red; }
.stat.warn { color: $amber; }
"""

# ─────────────────────────────────────────────────────────────
# File Picker Modal CSS
# ─────────────────────────────────────────────────────────────

FILE_PICKER_CSS = """
FilePickerModal {
    align: center middle;
}
#fp-dialog {
    width: 70;
    height: 30;
    background: #13161d;
    border: tall #4ade80;
    layout: vertical;
    padding: 1 2;
}
#fp-title {
    height: 2;
    color: #4ade80;
    text-style: bold;
    content-align: center middle;
    border-bottom: tall #1f2430;
    margin-bottom: 1;
}
#fp-tree {
    height: 1fr;
    background: #0c0e12;
    border: tall #1f2430;
    scrollbar-color: #2a2f3d;
    scrollbar-size: 1 1;
}
#fp-tree:focus {
    border: tall #4ade80;
}
#fp-selected {
    height: 2;
    color: #f59e0b;
    padding: 0 1;
    margin-top: 1;
    overflow: hidden;
}
#fp-btn-row {
    height: 3;
    layout: horizontal;
    align: right middle;
    margin-top: 1;
}
.fp-btn {
    width: 14;
    margin-left: 1;
    background: #13161d;
    border: tall #2a2f3d;
    color: #c9d1e0;
}
.fp-btn:hover { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
.fp-btn:focus { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
#fp-attach-btn {
    border: tall #4ade80;
    color: #4ade80;
    text-style: bold;
}
#fp-attach-btn:hover { background: #0d1a10; }
#fp-attach-btn:focus { background: #0d1a10; }
"""

# ─────────────────────────────────────────────────────────────
# Widgets
# ─────────────────────────────────────────────────────────────

class AgentChip(Static):
    def __init__(self, name: str, active: bool = False) -> None:
        super().__init__()
        self._name = name
        self.add_class("agent-chip")
        if active:
            self.add_class("active")

    def compose(self) -> ComposeResult:
        yield Label(self._name, classes="chip-name")
        yield Label("●" if "active" in self.classes else "○", classes="chip-dot")
        yield Label("~", classes="chip-status", id=f"chip-status-{self._name}")

    def on_click(self) -> None:
        self.app.set_active_agent(self._name)


class AppChip(Static):
    def __init__(self, name: str, connected: bool) -> None:
        super().__init__()
        self._name = name
        self.add_class("app-chip")
        if connected:
            self.add_class("on")

    def compose(self) -> ComposeResult:
        yield Label(self._name, classes="app-name")
        yield Label("●" if "on" in self.classes else "·", classes="app-dot")


# ─────────────────────────────────────────────────────────────
# File Picker Modal
# ─────────────────────────────────────────────────────────────

class FilePickerModal(ModalScreen):
    """A modal file browser that returns the selected absolute file path."""

    DEFAULT_CSS = FILE_PICKER_CSS

    def __init__(self) -> None:
        super().__init__()
        self._selected_path: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Container(id="fp-dialog"):
            yield Label("  📎  Attach File", id="fp-title")
            yield DirectoryTree(Path.home(), id="fp-tree")
            yield Label("No file selected", id="fp-selected")
            with Container(id="fp-btn-row"):
                yield Button("Cancel", id="fp-cancel-btn", classes="fp-btn")
                yield Button("Attach", id="fp-attach-btn", classes="fp-btn")

    def on_mount(self) -> None:
        self.query_one("#fp-tree", DirectoryTree).focus()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self._selected_path = str(event.path.resolve())
        self.query_one("#fp-selected", Label).update(
            f"  {self._selected_path}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp-cancel-btn":
            self.dismiss(None)
        elif event.button.id == "fp-attach-btn":
            self.dismiss(self._selected_path)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter" and self._selected_path:
            self.dismiss(self._selected_path)


class TabBtn(Static):
    def __init__(self, label: str, tab_id: str, active: bool = False) -> None:
        super().__init__(label, classes="tab-btn")
        self._label = label
        self._tabid = tab_id
        self.add_class("tab-btn")
        if active:
            self.add_class("active")

    def render(self) -> str:
        return self._label

    def on_click(self) -> None:
        self.app.switch_tab(self._tabid)


class MsgBlock(Static):
    def __init__(self, kind: str, body: str) -> None:
        super().__init__()
        icon, css = BLOCK_ICONS.get(kind, (".", "output_"))
        self.add_class("block", css)
        self._icon, self._kind, self._body = icon, kind, body

    def compose(self) -> ComposeResult:
        if self._kind.upper() != "OUTPUT":
            yield Label(f"{self._icon} {self._kind.upper()}", classes="blk-hdr")
        yield Label(escape(self._body), classes="blk-body",markup=False)  # ← escape here


class UserMsg(Static):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.add_class("msg-row")

    def compose(self) -> ComposeResult:
        yield Label(f"  YOU  {datetime.now().strftime('%H:%M')}", classes="usr-lbl")
        yield Label(escape(self._text), classes="usr-txt",markup=False)  # ← escape here


class AgentMsg(Static):
    def __init__(self, agent: str, blocks: list) -> None:
        super().__init__()
        self._agent, self._blocks = agent, blocks
        self.add_class("msg-row")

    def compose(self) -> ComposeResult:
        yield Label(f"  {escape(self._agent.upper())}  {datetime.now().strftime('%H:%M')}", classes="agt-lbl")
        for kind, body in self._blocks:
            yield MsgBlock(kind, body)


# ─────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────

class KattalaiApp(App):
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "quit",         "Quit"),
        Binding("ctrl+l", "clear",        "Clear"),
        Binding("ctrl+1", "tab_chat",     "Chat",     show=False),
        Binding("ctrl+2", "tab_space",    "Space",    show=False),
        Binding("ctrl+3", "tab_mind",     "Mind",     show=False),
        Binding("ctrl+4", "tab_terminal", "Terminal", show=False),
        Binding("ctrl+r", "refresh_mind", "Refresh",  show=False),
        Binding("escape", "focus_input",  "Focus",    show=False),
        Binding("ctrl+enter", "send_message", "Send"),
        Binding("ctrl+o", "attach_file",  "Attach File", show=False),
    ]

    active_agent: reactive[str]  = reactive("")
    active_tab:   reactive[str]  = reactive("chat-pane")
    is_thinking:  reactive[bool] = reactive(False)
    se_ready:     reactive[bool] = reactive(False)

    # ── SoulEngine state ──────────────────────────────────────
    _se_runtime   = None
    _se_user_id   = None
    _se_topic_id  = None
    _se_active_agent_id = None
    _se_active_agent_cursor_before = -1
    _se_active_agent_name = None
    _se_agent_ids: dict = {}
    _se_added:    set   = set()
    _msg_cursor:  int   = 0

    # ── compose ───────────────────────────────────────────────

    async def on_key(self, event: Key) -> None:
        if event.key == "ctrl+j" or event.key == "ctrl+enter":
            try:
                ta = self.query_one("#user-input", TextArea)
                if self.focused == ta:
                    text = ta.text.strip()
                    if not text:
                        return
                    event.stop()
                    ta.clear()
                    msgs = self.query_one("#messages", ScrollableContainer)
                    await msgs.mount(UserMsg(text))
                    msgs.scroll_end(animate=False)
                    if self.se_ready:
                        await self._se_send(text, msgs)
                    else:
                        await self._demo_respond(text, msgs)
            except NoMatches:
                pass

    def compose(self) -> ComposeResult:
        with Container(id="topbar"):
            with Container(id="topbar-left"):
                yield Label("Kattalai", id="logo")
                yield Label(" / Ai Coworker", id="logo-sub")

            with Container(id="tabbar"):
                for i, (tab, tabid) in enumerate(TABS):
                    yield TabBtn(tab, tab_id=tabid, active=(i == 0))
                    if i < len(TABS) - 1:
                        yield Static("|", classes="tab-sep")

            with Container(id="topbar-right"):
                yield Label("SE: init...", id="se-badge", classes="stat warn")

        # ── CHAT ──────────────────────────────────────
        with Container(id="chat-pane-box", classes="tab-pane show"):
            with ScrollableContainer(id="messages"):
                yield Static("")
            with Container(id="thinking"):
                yield Label("agent is thinking...", markup=False)
            with Container(id="input-row"):
                yield Select(
                    [(name, name) for name in AGENTS],
                    value=AGENTS[0],
                    id="agent-select",
                    allow_blank=False,
                )
                yield Label("க >", id="prompt-icon")
                yield TextArea(
                    placeholder="Ctrl+Enter to send  |  Ctrl+O to attach file",
                    id="user-input",
                )
                yield Button("🔗", id="attach-btn")

        # ── AGENT MIND ─────────────────────────────────
        with Container(id="agent-pane-box", classes="tab-pane"):
            with Container(classes="mind-col"):
                with ScrollableContainer(id="mind-history"):
                    yield Static("")

        # ── TERMINAL ───────────────────────────────────
        with Container(id="terminal-pane-box", classes="tab-pane"):
            yield RichLog(id="term-log", highlight=True, markup=False)
            with Container(id="term-input-row"):
                yield Static("")

    # ── Lifecycle ─────────────────────────────────────────────

    def on_mount(self) -> None:
        self.begin_capture_print(self.query_one("#term-log", RichLog))
        self.set_interval(30, self._tick_clock)
        self._se_added = set()
        if SE_AVAILABLE:
            self.init_soulengine()
        else:
            self._set_badge("SE: demo", "warn")
            self._log_term(f"[dim]--- SoulEngine not available — demo mode ---[/dim]")
        self._seed_terminal_header()

    def _tick_clock(self) -> None:
        try:
            self.query_one("#clock", Label).update(datetime.now().strftime("%a %d %b  %H:%M"))
        except NoMatches:
            pass

    def _set_badge(self, text: str, level: str = "ok") -> None:
        try:
            b = self.query_one("#se-badge", Label)
            b.update(text)
            b.remove_class("ok", "warn", "err")
            b.add_class(level)
        except NoMatches:
            pass

    def _update_stat(self, wid: str, text: str) -> None:
        try:
            self.query_one(f"#{wid}", Label).update(text)
        except NoMatches:
            pass

    # ── SoulEngine initialisation ─────────────────────────────

    @work(exclusive=True)
    async def chat_monitor(self) -> None:
        agent_cursor_before = -1
        try:
            logging.info("Chat Monitoring Started...")
            first_pass = True
            while True:
                cursor_before = await self._se_runtime.topic_history_len(self._se_topic_id)
                logging.info(f"self._se_topic_id{self._se_topic_id}")
                if not self._se_topic_id:
                    await asyncio.sleep(1)
                    continue
                if first_pass:
                    self._log_term(f"[#60a5fa]Topic Initiated = {self._se_topic_id}[/#60a5fa]")
                    first_pass = False

                while True:
                    await asyncio.sleep(0.5)
                    await self.agent_monitor()
                    new_len = await self._se_runtime.topic_history_len(self._se_topic_id)
                    if new_len > cursor_before:
                        break

                mem_iter = await self._se_runtime.iter_topic(
                    self._se_topic_id, cursor_before
                )
                mem_iter = json.loads(mem_iter)
                new_entries = list(mem_iter)
                self._msg_cursor = cursor_before + 1 + len(new_entries)
                self._update_stat("stat-topic", f"topic: {str(self._se_topic_id)[:8]}")

                logging.info(f"MEM{new_entries}")
                msgs = self.query_one("#messages", ScrollableContainer)
                if new_entries:
                    for mem in new_entries:
                        src     = mem['name']
                        content = mem['content']
                        if mem['role'] == "user":
                            continue
                        blocks  = parse_se_content(content)
                        await msgs.mount(AgentMsg(src, blocks))
                        msgs.scroll_end(animate=False)
                        self._inc_msg_stat(1)
                        self._log_term(f"[#4ade80]-> {src}: {content[:60]}…[/#4ade80]")
                else:
                    await msgs.mount(AgentMsg(self.active_agent, [
                        ("output", "(no response received — agent may be processing)")
                    ]))
                    msgs.scroll_end(animate=False)
        except Exception as e:
            logging.error(f"Chat Monitor Error:{str(e)}")

    async def agent_monitor(self) -> None:
        try:
            if not self._se_active_agent_id:
                self.is_thinking = False
                return self._se_active_agent_cursor_before
            if not self._se_topic_id or not self._se_active_agent_id:
                self.is_thinking = False
                return self._se_active_agent_cursor_before

            agent_status = await self._se_runtime.is_agent_working_on_topic(
                self._se_topic_id, self._se_active_agent_id
            )
            self.is_thinking = agent_status == True

            new_len = await self._se_runtime.agent_episode_len(
                self._se_topic_id, self._se_active_agent_id
            )
            if new_len <= self._se_active_agent_cursor_before and new_len > 0:
                return self._se_active_agent_cursor_before

            mem_iter = await self._se_runtime.iter_agent_episode(
                self._se_topic_id, self._se_active_agent_id,
                max(0, self._se_active_agent_cursor_before)
            )
            mem_iter = json.loads(mem_iter)
            new_entries = list(mem_iter)

            logging.info(f"Agent MEM{new_entries}")
            msgs = self.query_one("#mind-history", ScrollableContainer)
            if new_entries:
                for mem in new_entries:
                    src     = mem['name']
                    content = mem['content']
                    blocks  = parse_se_content(content)
                    await msgs.mount(AgentMsg(src, blocks))
                    msgs.scroll_end(animate=False)
            self._se_active_agent_cursor_before = new_len
            return self._se_active_agent_cursor_before
        except Exception as e:
            logging.error(f"Agent Monitor Error:{str(e)}")

    @work(exclusive=True)
    async def init_soulengine(self) -> None:
        log = self._log_term
        log("[dim]--- SoulEngine initialising ---[/dim]")
        try:
            self._se_runtime = GLOBAL_SE_RUNTIME
            log("[#4ade80]runtime created[/#4ade80]")

            self._se_user_id = await self._se_runtime.create_user("kattalaiUser")
            log(f"[#60a5fa]user_id = {self._se_user_id}[/#60a5fa]")

            self._se_topic_id = await self._se_runtime.create_topic_thread()
            log(f"[#60a5fa]topic_id = {self._se_topic_id}[/#60a5fa]")
            self._update_stat("stat-topic", f"topic: {str(self._se_topic_id)[:8]}")

            self.se_ready = True
            self._set_badge(f"Live: http://{se_bind}", "ok")
            log("[#4ade80]--- SoulEngine ready ---[/#4ade80]")

            self.chat_monitor()

        except Exception as e:
            self._set_badge("SE: error", "err")
            log(f"[bold #f87171]SE init error: {e}[/bold #f87171]")

    async def _add_agent_to_topic(self, name: str) -> None:
        if name is None:
            name = AGENTS[0]
            logging.info("Defaulting to First Agent")
        if not self.se_ready:
            logging.info("1 fails")
            return
        if name in self._se_added:
            logging.info("2 failed")
            return

        logging.info(f"Agent init to topic:{name}")
        if name is not None:
            if name not in self._se_agent_ids or self._se_agent_ids.get(name) is None:
                try:
                    logging.info(f"Deploying agent:{name}")
                    self._se_agent_ids[name] = await self._se_runtime.deploy_agent(name)
                except Exception as e:
                    self._log_term(f"[#f87171]Deploying agent error: {e}[/#f87171]")

        agent_id = self._se_agent_ids.get(name)
        if agent_id is None:
            logging.info("3 failed")
            return
        try:
            if self._se_active_agent_id:
                await self._se_runtime.remove_agent_from_topic(
                    self._se_topic_id, self._se_active_agent_id
                )
                self._log_term(f"[dim]agent {self._se_active_agent_name} removed from topic[/dim]")
                self._se_active_agent_cursor_before = -1
            logging.info(f"Adding agent {name}-{agent_id} to topic:{self._se_topic_id}")
            await self._se_runtime.add_agent_to_topic(self._se_topic_id, agent_id)
            self._se_active_agent_id = self._se_agent_ids[name]
            self._se_active_agent_name = name
            self._se_added.add(name)
            self._log_term(f"[dim]agent {name} added to topic[/dim]")
            self._se_active_agent_id = agent_id
        except Exception as e:
            self._log_term(f"[#f87171]add_agent_to_topic error: {e}[/#f87171]")

    def _mark_agent_live(self, name: str) -> None:
        try:
            lbl = self.query_one(f"#chip-status-{name}", Label)
            lbl.update("●")
            lbl.add_class("live")
        except NoMatches:
            pass

    # ── Tab management ────────────────────────────────────────

    def switch_tab(self, name: str) -> None:
        self.active_tab = name

    def watch_active_tab(self, val: str) -> None:
        pane_id = val
        panes = {"Chat": "chat-pane",
                 "Agent Mind": "agent-pane", "Terminal": "terminal-pane"}
        for tab_name, tab_id in panes.items():
            try:
                p = self.query_one(f"#{tab_id}-box")
                p.add_class("show") if tab_id == pane_id else p.remove_class("show")
            except NoMatches:
                logging.info(f"NoMatches{tab_id}-{pane_id}")

        for btn in self.query(TabBtn):
            btn.add_class("active") if btn._tabid == pane_id else btn.remove_class("active")
        if pane_id == "chat-pane":
            try:
                self.query_one("#user-input", TextArea).focus()
            except NoMatches:
                pass
        elif pane_id == "terminal-pane":
            try:
                self.query_one("#term-input", Input).focus()
            except NoMatches:
                pass
        elif pane_id == "agent-pane" and self.se_ready:
            pass

    # ── Agent management ──────────────────────────────────────

    def set_active_agent(self, name: str) -> None:
        self.active_agent = name

    def watch_active_agent(self, val: str) -> None:
        logging.info(f"Active Agent:{val}")
        if val == "":
            return None
        try:
            sel = self.query_one("#agent-select", Select)
            if sel.value != val:
                sel.value = val
        except NoMatches:
            pass
        logging.info(f"watch_active_agentActive Agent:{val}")
        asyncio.create_task(self._add_agent_to_topic(val))

    # ── Thinking indicator ────────────────────────────────────

    def watch_is_thinking(self, val: bool) -> None:
        try:
            t = self.query_one("#thinking")
            t.add_class("show") if val else t.remove_class("show")
        except NoMatches:
            pass

    # ── Chat input ────────────────────────────────────────────

    @on(Select.Changed, "#agent-select")
    def handle_agent_select(self, event: Select.Changed) -> None:
        if event.value:
            self.set_active_agent(str(event.value))

    @on(Button.Pressed, "#attach-btn")
    def handle_attach_btn(self, event: Button.Pressed) -> None:
        self.action_attach_file()

    async def _se_send(self, text: str, msgs: ScrollableContainer) -> None:
        self._log_term(f"[bold #f59e0b]$ runtime.insert_message(topic, user, ...)[/bold #f59e0b]")
        logging.info(f"se send:{self._se_active_agent_name}")
        if self._se_active_agent_name is None:
            self._se_active_agent_name = AGENTS[0]
        if not self._se_active_agent_id:
            logging.info(f"se send adding agent:{self._se_active_agent_name}")
            await self._add_agent_to_topic(self._se_active_agent_name)

        try:
            await self._se_runtime.insert_message(
                self._se_topic_id, self._se_user_id, text
            )
            self._log_term(f"[#4ade80]-> message inserted[/#4ade80]")
        except Exception as e:
            self._log_term(f"[#f87171]SE send error: {e}[/#f87171]")
            await msgs.mount(AgentMsg(self.active_agent, [("output", f"Error: {e}")]))
            msgs.scroll_end(animate=False)

    async def _demo_respond(self, text: str, msgs: ScrollableContainer) -> None:
        blocks = [
            ("thought", f"Parsing: \"{text[:55]}{'...' if len(text) > 55 else ''}\""),
            ("output",  "Demo mode active — SoulEngine not loaded.\nInstall soulengine and torch to enable live responses."),
        ]
        await msgs.mount(AgentMsg(self.active_agent, blocks))
        msgs.scroll_end(animate=False)
        self._inc_msg_stat(1)

    # ── Terminal ──────────────────────────────────────────────

    def _seed_terminal_header(self) -> None:
        self._log_term(f"[dim]--- Cowork agent shell  {datetime.now().strftime('%Y-%m-%d %H:%M')} ---[/dim]")
        self._log_term(f"[dim]SoulEngine available: {'YES' if SE_AVAILABLE else 'NO (demo mode)'}[/dim]")
        self._log_term("[dim]type 'help' for commands[/dim]")

    def _log_term(self, text: str) -> None:
        try:
            self.query_one("#term-log", RichLog).write(text)
        except NoMatches:
            pass

    @on(Input.Submitted, "#term-input")
    async def handle_term(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        if not cmd:
            return
        self.query_one("#term-input", Input).clear()
        log = self.query_one("#term-log", RichLog)
        log.write(f"[bold #f59e0b]$ {cmd}[/bold #f59e0b]")
        await self._dispatch_term(cmd, log)
        log.scroll_end(animate=False)

    async def _dispatch_term(self, cmd: str, log: RichLog) -> None:
        w = cmd.split()
        verb = w[0] if w else ""

        if verb == "se.status":
            if self.se_ready:
                tlen = await self._se_runtime.topic_history_len(self._se_topic_id)
                log.write(f"[#4ade80]runtime: live[/#4ade80]")
                log.write(f"  user_id   = {self._se_user_id}")
                log.write(f"  topic_id  = {self._se_topic_id}")
                log.write(f"  topic_len = {tlen}")
                log.write(f"  agents    = {list(self._se_agent_ids.keys())}")
                log.write(f"  in_topic  = {list(self._se_added)}")
            else:
                log.write("[#f59e0b]runtime: demo / not ready[/#f59e0b]")

        elif verb == "se.history":
            if not self.se_ready:
                log.write("[#f87171]SE not ready[/#f87171]"); return
            try:
                mem_iter = await self._se_runtime.iter_topic(self._se_topic_id, 0)
                for i, mem in enumerate(mem_iter):
                    src     = mem.get_source_name()
                    content = mem.get_content()
                    colour  = "#4ade80" if src != "CoworkUser" else "#60a5fa"
                    log.write(f"[dim]{i:03d}[/dim] [{colour}]{src}[/{colour}]: {content[:100]}")
            except Exception as e:
                log.write(f"[#f87171]error: {e}[/#f87171]")

        elif verb == "se.memory":
            if not self.se_ready:
                log.write("[#f87171]SE not ready[/#f87171]"); return
            try:
                tlen = await self._se_runtime.topic_history_len(self._se_topic_id)
                log.write(f"[#60a5fa]topic_history_len = {tlen}[/#60a5fa]")
            except Exception as e:
                log.write(f"[#f87171]error: {e}[/#f87171]")

        elif verb == "se.agents":
            for name, aid in self._se_agent_ids.items():
                active = "●" if name in self._se_added else "○"
                log.write(f"  {active} {name:10s}  id={aid}")

        elif verb == "se.add" and len(w) > 1:
            name = w[1]
            if name not in AGENTS:
                log.write(f"[#f87171]unknown agent '{name}'. Available: {AGENTS}[/#f87171]"); return
            await self._add_agent_to_topic(name)
            log.write(f"[#4ade80]-> {name} added to topic[/#4ade80]")

        elif verb == "se.send" and len(w) > 1:
            if not self.se_ready:
                log.write("[#f87171]SE not ready[/#f87171]"); return
            msg = " ".join(w[1:])
            await self._se_runtime.insert_message(self._se_topic_id, self._se_user_id, msg)
            log.write(f"[#4ade80]-> message sent: {msg[:60]}[/#4ade80]")

        elif verb == "se.topic.len":
            if not self.se_ready:
                log.write("[#f87171]SE not ready[/#f87171]"); return
            n = await self._se_runtime.topic_history_len(self._se_topic_id)
            log.write(f"[#4ade80]-> {n}[/#4ade80]")

        elif verb == "help":
            log.write("[#60a5fa]SoulEngine commands:[/#60a5fa]")
            log.write("  se.status          — runtime info")
            log.write("  se.agents          — deployed agents + topic membership")
            log.write("  se.add <name>      — add agent to topic thread")
            log.write("  se.send <text>     — insert message directly")
            log.write("  se.history         — full topic iter_topic dump")
            log.write("  se.memory          — topic_history_len")
            log.write("  se.topic.len       — topic length")
            log.write("[#60a5fa]App commands:[/#60a5fa]")
            log.write("  agents.list  clear")

        elif verb == "clear":
            log.clear()
            log.write("[dim]--- cleared ---[/dim]")

        elif verb == "agents.list":
            for name in AGENTS:
                aid = self._se_agent_ids.get(name, "—")
                live = "●" if name in self._se_added else "○"
                log.write(f"  {live} {name:12s} id={aid}")

        else:
            log.write(f"[#f87171]unknown: '{cmd}'  (try 'help')[/#f87171]")

    # ── Helpers ───────────────────────────────────────────────

    def _inc_msg_stat(self, n: int = 1) -> None:
        try:
            lbl = self.query_one("#stat-msgs", Label)
            cur = int(lbl.renderable.split(":")[1].strip())
            lbl.update(f"msgs: {cur + n}")
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────

    async def action_clear(self) -> None:
        if self.active_tab == "chat-pane":
            msgs = self.query_one("#messages", ScrollableContainer)
            await msgs.query("*").remove()
            await msgs.mount(Static(""))
        elif self.active_tab == "terminal-pane":
            log = self.query_one("#term-log", RichLog)
            log.clear()
            log.write("[dim]--- cleared ---[/dim]")

    def action_refresh_mind(self) -> None:
        if self.active_tab == "agent-pane":
            pass

    def action_tab_chat(self)     -> None: self.switch_tab("chat-pane")
    def action_tab_mind(self)     -> None: self.switch_tab("agent-pane")
    def action_tab_terminal(self) -> None: self.switch_tab("terminal-pane")

    def action_focus_input(self) -> None:
        try:
            if self.active_tab == "Terminal":
                self.query_one("#term-input", Input).focus()
            else:
                self.query_one("#user-input", TextArea).focus()
        except NoMatches:
            pass

    def action_attach_file(self) -> None:
        """Open the file picker modal and append the chosen absolute path to the input."""
        async def _open() -> None:
            def _on_dismiss(path: Optional[str]) -> None:
                if not path:
                    return
                try:
                    ta = self.query_one("#user-input", TextArea)
                    current = ta.text
                    separator = "\n" if current.strip() else ""
                    ta.load_text(current + separator + f"FilePath:{path}")
                    ta.move_cursor(ta.document.end)
                    ta.focus()
                except NoMatches:
                    pass
            await self.push_screen(FilePickerModal(), callback=_on_dismiss)
        asyncio.create_task(_open())


# ─────────────────────────────────────────────────────────────
# CLI helpers
# ─────────────────────────────────────────────────────────────

def open_folder():
    folder = Path(__file__).parent
    if sys.platform == "win32":
        subprocess.Popen(f'explorer "{folder}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def setup():
    os.chdir(Path(__file__).parent)
    base = Path(__file__).parent
    folders = ["apps", "configs", "model_assets", "prompts"]

    if all((base / f).exists() for f in folders):
        print("Already set up.")
        return

    print("Downloading assets from GitHub...")
    url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{BRANCH}.zip"
    zip_path = base / "temp.zip"
    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as z:
        for folder in folders:
            for file in z.namelist():
                if file.startswith(f"kattalai-{BRANCH}/{folder}/"):
                    z.extract(file, base / "temp_extract")

    extract_root = base / "temp_extract" / f"kattalai-{BRANCH}"
    for folder in folders:
        src = extract_root / folder
        dst = base / folder
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  ✓ {folder}")
        else:
            print(f"  ✗ {folder} not found in repo")

    zip_path.unlink()
    shutil.rmtree(base / "temp_extract")
    print("Setup complete. Run 'kattalai' to start.")


def upgrade():
    os.chdir(Path(__file__).parent)
    base = Path(__file__).parent
    folders = ["apps", "configs", "model_assets", "prompts"]

    print("Upgrading kattalai package...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "kattalai"],
        check=True
    )
    print("  ✓ Package upgraded")

    print("Removing existing assets...")
    for folder in folders:
        dst = base / folder
        if dst.exists():
            shutil.rmtree(dst)
            print(f"  ✓ Removed {folder}")

    print("Downloading fresh assets from GitHub...")
    url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{BRANCH}.zip"
    zip_path = base / "temp.zip"
    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as z:
        for folder in folders:
            for file in z.namelist():
                if file.startswith(f"kattalai-{BRANCH}/{folder}/"):
                    z.extract(file, base / "temp_extract")

    extract_root = base / "temp_extract" / f"kattalai-{BRANCH}"
    for folder in folders:
        src = extract_root / folder
        dst = base / folder
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  ✓ {folder}")
        else:
            print(f"  ✗ {folder} not found in repo")

    zip_path.unlink()
    shutil.rmtree(base / "temp_extract")
    print("Upgrade complete. Run 'kattalai' to start.")


def main():
    os.chdir(Path(__file__).parent)
    setup()
    asyncio.run(load_run_time())
    KattalaiApp().run()


if __name__ == "__main__":
    main()