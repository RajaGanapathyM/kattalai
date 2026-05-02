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
logging.basicConfig(filename="newdebug.log", level=logging.INFO)

SE_AVAILABLE = False
GLOBAL_SE_RUNTIME = None
try:
    import torch
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(_torch_lib):
        os.add_dll_directory(_torch_lib)
    from soulengine import PyRuntime
    SE_AVAILABLE = True
except Exception as e:
    pass  # SE unavailability is shown in badge

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
# Static data
# ─────────────────────────────────────────────────────────────

AGENTS = []
se_bind = "127.0.0.1:3077"


async def load_run_time():
    global AGENTS, GLOBAL_SE_RUNTIME
    GLOBAL_SE_RUNTIME = await PyRuntime.create(bind=se_bind)
    AGENTS = await GLOBAL_SE_RUNTIME.get_agent_list()


TABS = [("Chat", "chat-pane"),
        ("Agent Thoughts", "agent-pane"),
        ("Logs", "terminal-pane")]

BLOCK_ICONS = {
    "thoughts":         ("◆", "thoughts"),
    "terminal":         ("$", "terminal"),
    "output":           ("*", "output_"),
    "validation":       ("✓", "validation"),
    "followup_context": ("→", "followup"),
}


def parse_se_content(content: str) -> list[tuple[str, str]]:
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
$bg:       #0b0d11;
$surf:     #111318;
$surf2:    #161a22;
$bord:     #1e2330;
$bord2:    #272d3e;
$text:     #c8d0e0;
$muted:    #48526a;
$green:    #4ade80;
$blue:     #60a5fa;
$amber:    #f59e0b;
$purple:   #e879f9;
$red:      #f87171;
$cyan:     #22d3ee;
$text-muted: #6b7280;

$topic-active-bg:   #1a2135;
$topic-hover-bg:    #141926;

Screen { background: $bg; color: $text; layout: horizontal; }

/* ═══════════════════════════════════════════
   LEFT PANEL
   ═══════════════════════════════════════════ */

#left-panel {
    width: 30;
    min-width: 22;
    max-width: 40;
    background: $surf;
    border-right: tall $bord;
    layout: vertical;
    height: 100%;
}

#left-header {
    height: 4;
    background: $surf2;
    border-bottom: tall $bord;
    layout: horizontal;
    align: center middle;
    padding: 0 1;
}

#left-title {
    width: 1fr;
    color: $text;
    text-style: bold;
    padding-left: 1;
    align: center middle;
}

#topic-search-row {
    height: 5;
    background: $surf;
    padding: 0 0;
    layout: horizontal;
    align: center middle;
}
#topic-search {
    width: 1fr;
    background: $bg;
    border: tall $bord2;
    color: $text;
    height: 3;
    padding: 0 1;
}
#topic-search:focus { border: tall $green; }


#topic-list {
    width: 100%;
    height: 1fr;
    background: $surf;
    scrollbar-color: $bord2;
    scrollbar-size: 1 1;
}

#new-episode-btn {
    width: 100%;
    height: 3;
    background: $surf;
    border-bottom: tall $bord;
    border-top: tall $bord;
    color: $muted;
    content-align: left middle;
    padding: 0 2;
}
#new-episode-btn:hover { color: $green; background: $surf2; }
#new-episode-btn:focus { color: $green; background: $surf2; border: none; border-bottom: tall $bord; }

.topic-row {
    width: 100%;
    height: 4;
    background: $surf;
    border-bottom: tall $bord;
    layout: horizontal;
    align: center middle;
    padding: 0 1;
}
.topic-row:hover { background: $topic-hover-bg; }
.topic-row.active-topic { background: $topic-active-bg; border-left: thick $green; }

.topic-avatar {
    width: 4;
    height: 3;
    background: $bg;
    border: tall $bord2;
    content-align: center middle;
    color: $cyan;
    text-style: bold;
    min-width: 4;
    max-width: 4;
    min-height: 3;
    max-height: 3;
}
.topic-row.active-topic .topic-avatar { border: tall $green; color: $green; }

.topic-meta {
    width: 1fr;
    layout: vertical;
    padding-left: 1;
    height: 4;
    overflow: hidden;
}
.topic-name {
    color: $text;
    text-style: bold;
    height: 2;
}
.topic-preview {
    color: $muted;
    height: 1;
    overflow: hidden;
}
.topic-row.active-topic .topic-name { color: $green; }

.topic-side {
    width: 5;
    layout: vertical;
    align: right top;
    height: 4;
    padding-top: 0;
}
.topic-time {
    color: $muted;
    height: 2;
    text-align: right;
}
.topic-unread {
    color: $bg;
    background: $green;
    height: 2;
    width: 3;
    content-align: center middle;
    text-align: right;
    display: none;
}
.topic-unread.has-unread { display: block; }

#left-footer {
    height: 3;
    background: $surf2;
    border-top: tall $bord;
    layout: horizontal;
    align: center middle;
    padding: 0 1;
}
#se-badge {
    width: 1fr;
    color: $text-muted;
}

/* ═══════════════════════════════════════════
   RIGHT PANEL
   ═══════════════════════════════════════════ */

#right-panel {
    width: 1fr;
    layout: vertical;
    height: 100%;
    background: $bg;
}

#topic-header {
    height: 4;
    background: $surf2;
    border-bottom: tall $bord;
    layout: horizontal;
    align: center middle;
    padding: 0 2;
}

#topic-header-hash {
    width: 3;
    color: $green;
    text-style: bold;
    content-align: center middle;
}
#topic-header-name {
    color: $green;
    text-style: bold;
}
#topic-header-meta {
    width: 1fr;
    layout: vertical;
    height: 3;
}
#topic-header-name {
    color: $text;
    text-style: bold;
    height: 2;
}
#topic-header-status {
    color: $muted;
    height: 1;
}
#topic-header-actions {
    width: 18;
    layout: horizontal;
    align: right middle;
}

#tabbar {
    layout: horizontal;
    width: 100%;
    height: 3;
    background: $surf;
    border-bottom: tall $bord;
    padding: 0 2;
    align: left middle;
}

.tab-btn {
    width: auto;
    height: 3;
    padding: 0 3;
    color: $text-muted;
    background: transparent;
    content-align: center middle;
}
.tab-btn:hover  { color: $text; background: #1a1f2e; }
.tab-btn.active { color: $green; text-style: bold; border-bottom: tall $green; }
.tab-btn:focus  { background: transparent; }
.tab-sep { width: 1; color: $bord2; content-align: center middle; }

.tab-pane { width: 100%; height: 1fr; display: none; }
.tab-pane.show { display: block; }

/* ════ CHAT ════ */
#chat-pane-box { layout: vertical; }
#messages {
    width: 100%;
    height: 1fr;
    padding: 1 2;
    background: $bg;
    scrollbar-color: $bord2;
    scrollbar-size: 1 1;
}
.msg-row { width: 100%; margin-bottom: 2; layout: vertical; }
.usr-lbl { color: $muted; text-style: italic; }
.usr-txt {
    background: #151b2e;
    border-left: thick $blue;
    padding: 0 2;
    color: $text;
    margin-bottom: 1;
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

#thinking {
    height: 2;
    background: $surf;
    border-top: tall $bord2;
    padding: 0 2;
    layout: horizontal;
    align: center middle;
    display: none;
}
#thinking.show { display: block; }

#input-row {
    height: 5;
    background: $surf;
    border-top: tall $bord2;
    overflow: auto;
    padding: 0 2;
    layout: horizontal;
    align: center middle;
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
#agent-select > SelectCurrent { background: transparent; color: $green; border: none; text-style: bold; padding: 0 1; }
#agent-select > SelectCurrent:focus { background: transparent; border: none; }
SelectOverlay { background: $surf; border: tall $green; color: $text; }
SelectOverlay > .option-list--option-highlighted { background: #1a2f1a; color: $green; }
SelectOverlay > .option-list--option { padding: 0 1; color: $text; }
#user-input { width: 1fr; background: transparent; border: none; color: $text; padding: 0; }
#user-input:focus { border: none; background: transparent; }

#attach-btn {
    width: 7; height: 3; min-width: 3;
    background: #13161d; border: tall #2a2f3d;
    color: #4a5270; margin-left: 1; padding: 0;
    content-align: center middle;
}
#attach-btn:hover { border: tall #4ade80; color: #4ade80; background: #0d1a10; }
#attach-btn:focus { border: tall #4ade80; color: #4ade80; background: #0d1a10; }

/* ════ AGENT MIND ════ */
#agent-pane-box { layout: horizontal; padding: 1; background: $bg; }
.mind-col { width: 1fr; layout: vertical; margin-right: 1; height: 100%; }
.mind-col:last-child { margin-right: 0; }
#mind-history {
    width: 100%; height: 1fr; padding: 1 2;
    background: $bg; scrollbar-color: $bord2; scrollbar-size: 1 1;
}

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

/* ════ EMPTY STATE ════ */
#no-topic-pane {
    width: 100%;
    height: 100%;
    layout: vertical;
    align: center middle;
    background: $bg;
}
.empty-icon  { color: $muted; text-align: center; width: 100%; }
.empty-title { color: $text; text-style: bold; text-align: center; width: 100%; }
.empty-hint  { color: $muted; text-align: center; width: 100%; }

/* ════ NEW TOPIC MODAL ════ */
NewTopicModal { align: center middle; }
#nt-dialog {
    width: 50;
    height: 16;
    background: #13161d;
    border: tall #4ade80;
    layout: vertical;
    padding: 1 2;
}
#nt-title {
    height: 2;
    color: #4ade80;
    text-style: bold;
    content-align: center middle;
    border-bottom: tall #1f2430;
    margin-bottom: 1;
}
#nt-name-label { color: #6b7280; height: 1; }
#nt-name-input {
    width: 100%;
    height: 3;
    background: #0c0e12;
    border: tall #2a2f3d;
    color: #c9d1e0;
    margin-bottom: 1;
}
#nt-name-input:focus { border: tall #4ade80; }
#nt-btn-row {
    height: 3;
    layout: horizontal;
    align: right middle;
}
.nt-btn {
    width: 12;
    margin-left: 1;
    background: #13161d;
    border: tall #2a2f3d;
    color: #c9d1e0;
}
.nt-btn:hover { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
.nt-btn:focus { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
#nt-create-btn { border: tall #4ade80; color: #4ade80; text-style: bold; }
#nt-create-btn:hover { background: #0d1a10; }

/* ════ FILE PICKER MODAL ════ */
FilePickerModal { align: center middle; }
#fp-dialog {
    width: 70; height: 30;
    background: #13161d; border: tall #4ade80;
    layout: vertical; padding: 1 2;
}
#fp-title { height: 2; color: #4ade80; text-style: bold; content-align: center middle; border-bottom: tall #1f2430; margin-bottom: 1; }
#fp-tree { height: 1fr; background: #0c0e12; border: tall #1f2430; scrollbar-color: #2a2f3d; scrollbar-size: 1 1; }
#fp-tree:focus { border: tall #4ade80; }
#fp-selected { height: 2; color: #f59e0b; padding: 0 1; margin-top: 1; overflow: hidden; }
#fp-btn-row { height: 3; layout: horizontal; align: right middle; margin-top: 1; }
.fp-btn { width: 14; margin-left: 1; background: #13161d; border: tall #2a2f3d; color: #c9d1e0; }
.fp-btn:hover { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
.fp-btn:focus { background: #1a1f2e; border: tall #4ade80; color: #4ade80; }
#fp-attach-btn { border: tall #4ade80; color: #4ade80; text-style: bold; }
#fp-attach-btn:hover { background: #0d1a10; }
"""

# ─────────────────────────────────────────────────────────────
# Topic data model
# ─────────────────────────────────────────────────────────────


class TopicSession:
    """Holds all SE state and message history for one topic thread."""

    _id_counter = 0

    def __init__(self, name: str):
        TopicSession._id_counter += 1
        self.local_id = TopicSession._id_counter
        self.name = name
        self.created_at = datetime.now()
        self.last_msg_time = datetime.now()
        self.last_preview = "New episode"
        self.unread = 0

        # SE state per topic
        self.se_topic_id = None
        self.se_user_id = None
        self.se_active_agent_id = None
        self.se_active_agent_name = None
        self.se_active_agent_cursor_before = -1
        self.se_agent_ids: dict = {}
        self.se_added: set = set()
        self.msg_cursor = 0

        # Per-topic message widget snapshots
        # We store (role, data) tuples: role="user" -> text str, role="agent" -> (agent_name, blocks)
        self.message_log: list[tuple[str, object]] = []

        # Per-topic mind history
        self.mind_log: list[tuple[str, list]] = []  # (agent_name, blocks)

        # Active tab within this topic
        self.active_tab = "chat-pane"

        # Guard: only one monitor worker per topic
        self._monitor_started = False

        # FIX: guard to prevent monitor double-mounting during _restore_topic_messages
        self._restoring = False
        self._mind_restoring = False

    @property
    def avatar_letter(self) -> str:
        return self.name[0].upper() if self.name else "T"

    @property
    def time_str(self) -> str:
        return self.last_msg_time.strftime("%H:%M")


# ─────────────────────────────────────────────────────────────
# Modals
# ─────────────────────────────────────────────────────────────


class NewTopicModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Container(id="nt-dialog"):
            yield Label("  +  New Episode", id="nt-title")
            yield Label("Episode name", id="nt-name-label")
            yield Input(placeholder="e.g. Research, Code Review, Planning…", id="nt-name-input")
            with Container(id="nt-btn-row"):
                yield Button("Cancel", id="nt-cancel-btn", classes="nt-btn")
                yield Button("Create", id="nt-create-btn", classes="nt-btn")

    def on_mount(self) -> None:
        self.query_one("#nt-name-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nt-cancel-btn":
            self.dismiss(None)
        elif event.button.id == "nt-create-btn":
            name = self.query_one("#nt-name-input", Input).value.strip()
            self.dismiss(name if name else "Episode")

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            name = self.query_one("#nt-name-input", Input).value.strip()
            self.dismiss(name if name else "Episode")


class FilePickerModal(ModalScreen):
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

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._selected_path = str(event.path.resolve())
        self.query_one("#fp-selected", Label).update(f"  {self._selected_path}")

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


# ─────────────────────────────────────────────────────────────
# Widgets
# ─────────────────────────────────────────────────────────────


class TopicRow(Static):
    """A single row in the left topic list."""

    def __init__(self, topic: TopicSession, active: bool = False) -> None:
        super().__init__()
        self._topic = topic
        self.add_class("topic-row")
        if active:
            self.add_class("active-topic")

    def compose(self) -> ComposeResult:
        with Container(classes="topic-meta"):
            yield Label(f"#{self._topic.name}", classes="topic-name")
            preview_text = self._topic.last_preview
            if len(preview_text) > 26:
                preview_text = preview_text[:26] + "…"
            yield Label(preview_text, classes="topic-preview",
                        id=f"topic-preview-{self._topic.local_id}")
        with Container(classes="topic-side"):
            yield Label(self._topic.time_str, classes="topic-time",
                        id=f"topic-time-{self._topic.local_id}")
            unread_lbl = Label(str(self._topic.unread) if self._topic.unread else "",
                               classes="topic-unread",
                               id=f"topic-unread-{self._topic.local_id}")
            if self._topic.unread:
                unread_lbl.add_class("has-unread")
            yield unread_lbl

    def on_click(self) -> None:
        self.app.switch_topic(self._topic.local_id)


class TabBtn(Static):
    def __init__(self, label: str, tab_id: str, active: bool = False) -> None:
        super().__init__(label, classes="tab-btn")
        self._label = label
        self._tabid = tab_id
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
        yield Label(escape(self._body), classes="blk-body", markup=False)


class UserMsg(Static):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.add_class("msg-row")

    def compose(self) -> ComposeResult:
        yield Label(f"  YOU  {datetime.now().strftime('%H:%M')}", classes="usr-lbl")
        yield Label(escape(self._text), classes="usr-txt", markup=False)


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
from rich.style import Style as RichStyle

class SearchInput(Input):
    """Input with guaranteed visible placeholder and typed text."""
    def get_component_rich_style(self, name: str, *, partial: bool = False) -> RichStyle:
        if name == "input--value":
            return RichStyle(color="#c8d0e0")
        if name == "input--placeholder":
            return RichStyle(color="#48526a")
        if name == "input--cursor":
            return RichStyle(color="#0b0d11", bgcolor="#4ade80")
        if name == "input--highlight":
            return RichStyle(bgcolor="#1a2f1a")
        return super().get_component_rich_style(name, partial=partial)

    DEFAULT_CSS = """
    SearchInput {
        width: 1fr;
        height: 5;
        background: #0b0d11;
        border: tall #1e2330;
        color: #c8d0e0;
        height: 2;
        padding: 0 1;
    }
    SearchInput:focus { border: tall #4ade80; }
    """


class KattalaiApp(App):
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q",      "quit",          "Quit"),
        Binding("ctrl+l",      "clear",         "Clear"),
        Binding("ctrl+n",      "new_topic",     "New Episode"),
        Binding("ctrl+1",      "tab_chat",      "Chat",     show=False),
        Binding("ctrl+2",      "tab_mind",      "Mind",     show=False),
        Binding("ctrl+3",      "tab_terminal",  "Terminal", show=False),
        Binding("ctrl+o",      "attach_file",   "Attach",   show=False),
        Binding("escape",      "focus_input",   "Focus",    show=False),
        Binding("ctrl+up",     "prev_topic",    "Prev episode", show=False),
        Binding("ctrl+down",   "next_topic",    "Next episode", show=False),
        Binding("ctrl+j",      "send_message",  "Send message", show=False),
    ]

    active_tab:      reactive[str]  = reactive("chat-pane")
    is_thinking:     reactive[bool] = reactive(False)
    se_ready:        reactive[bool] = reactive(False)
    active_topic_id: reactive[int]  = reactive(-1)

    _se_runtime = None
    _topics: list[TopicSession] = []
    _topic_map: dict[int, TopicSession] = {}

    # ── compose ───────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── LEFT PANEL ────────────────────────────────────────
        with Container(id="left-panel"):
            with Container(id="topic-search-row"):
                yield Input(placeholder="Find topic…", id="topic-search")
            with ScrollableContainer(id="topic-list"):
                yield Button("⊕  new episode  ·  ctrl+n", id="new-episode-btn")
            with Container(id="left-footer"):
                yield Label("SE: init…", id="se-badge", classes="stat warn")

        # ── RIGHT PANEL ───────────────────────────────────────
        with Container(id="right-panel"):
            with Container(id="topic-header"):
                yield Label("#", id="topic-header-hash")
                with Container(id="topic-header-meta"):
                    yield Label("select an episode", id="topic-header-name")
                    yield Label("no episode selected", id="topic-header-status")
                with Container(id="topic-header-actions"):
                    pass

            with Container(id="tabbar"):
                for i, (tab, tabid) in enumerate(TABS):
                    yield TabBtn(tab, tab_id=tabid, active=(i == 0))
                    if i < len(TABS) - 1:
                        yield Static("|", classes="tab-sep")

            # Empty state
            with Container(id="no-topic-pane"):
                yield Label("◇", classes="empty-icon")
                yield Label("No episode open", classes="empty-title")
                yield Label("Press Ctrl+N or click '+ New Episode' to start", classes="empty-hint")

            # ── CHAT ────────────────────────────────────────
            with Container(id="chat-pane-box", classes="tab-pane"):
                with ScrollableContainer(id="messages"):
                    yield Static("")
                with Container(id="thinking"):
                    yield Label("agent is thinking…", markup=False)
                with Container(id="input-row"):
                    yield Select(
                        [(name, name) for name in AGENTS] if AGENTS else [("—", "—")],
                        value=AGENTS[0] if AGENTS else "—",
                        id="agent-select",
                        allow_blank=False,
                    )
                    yield Label("க >", id="prompt-icon")
                    yield TextArea(
                        placeholder="Ctrl+Enter to send  |  Ctrl+O to attach file",
                        id="user-input",
                    )
                    yield Button("🔗", id="attach-btn")

            # ── AGENT MIND ──────────────────────────────────
            with Container(id="agent-pane-box", classes="tab-pane"):
                with Container(classes="mind-col"):
                    with ScrollableContainer(id="mind-history"):
                        yield Static("")

            # ── TERMINAL ────────────────────────────────────
            with Container(id="terminal-pane-box", classes="tab-pane"):
                yield RichLog(id="term-log", highlight=True, markup=False)
                with Container(id="term-input-row"):
                    yield Static("$ ", id="term-prompt")
                    yield Input(placeholder="help", id="term-input")

    # ── Lifecycle ─────────────────────────────────────────────

    def on_mount(self) -> None:
        self._show_topic_workspace(False)
        if SE_AVAILABLE:
            self.init_soulengine()
        else:
            self._set_badge("SE: demo", "warn")
            self._log_term("[dim]--- SoulEngine not available — demo mode ---[/dim]")
        self._seed_terminal_header()

    def _show_topic_workspace(self, show: bool) -> None:
        try:
            tabbar = self.query_one("#tabbar")
            no_topic = self.query_one("#no-topic-pane")
            chat = self.query_one("#chat-pane-box")
            mind = self.query_one("#agent-pane-box")
            term = self.query_one("#terminal-pane-box")

            if show:
                tabbar.display = True
                no_topic.display = False
                self._apply_tab(self.active_tab)
            else:
                tabbar.display = False
                no_topic.display = True
                chat.display = False
                mind.display = False
                term.display = False
        except NoMatches:
            pass

    # ── Topic management ──────────────────────────────────────

    async def _create_topic(self, name: str) -> TopicSession:
        topic = TopicSession(name)
        self._topics.append(topic)
        self._topic_map[topic.local_id] = topic

        if self.se_ready and self._se_runtime:
            try:
                topic.se_user_id = await self._se_runtime.create_user(f"kattalaiUser_{topic.local_id}")
                topic.se_topic_id = await self._se_runtime.create_topic_thread()
                self._log_term(f"[#4ade80]episode '{name}' -> se_topic={topic.se_topic_id}[/#4ade80]")
            except Exception as e:
                self._log_term(f"[#f87171]SE topic init error: {e}[/#f87171]")

        topic_list = self.query_one("#topic-list", ScrollableContainer)
        await topic_list.mount(TopicRow(topic))

        self.switch_topic(topic.local_id)
        return topic

    def switch_topic(self, local_id: int) -> None:
        if local_id == self.active_topic_id:
            return
        self.active_topic_id = local_id

    def watch_active_topic_id(self, val: int) -> None:
        if val == -1:
            self._show_topic_workspace(False)
            return

        topic = self._topic_map.get(val)
        if not topic:
            return

        topic.unread = 0
        self._refresh_topic_row(topic)

        try:
            self.query_one("#topic-header-name", Label).update(topic.name)
            agent_name = topic.se_active_agent_name or "No agent"
            self.query_one("#topic-header-status", Label).update(
                f"agent: {agent_name}  |  {topic.se_topic_id or 'pending'}"
            )
        except NoMatches:
            pass

        # Highlight active row
        for row in self.query(TopicRow):
            if row._topic.local_id == val:
                row.add_class("active-topic")
            else:
                row.remove_class("active-topic")

        self._show_topic_workspace(True)
        self.switch_tab(topic.active_tab)

        # Restore this topic's per-topic message history into the shared DOM
        asyncio.create_task(self._restore_topic_messages(topic))
        asyncio.create_task(self._restore_mind_messages(topic))

        if topic.se_active_agent_name:
            try:
                sel = self.query_one("#agent-select", Select)
                sel.value = topic.se_active_agent_name
            except NoMatches:
                pass

        # Only start one monitor per topic
        if self.se_ready and topic.se_topic_id and not topic._monitor_started:
            topic._monitor_started = True
            self.chat_monitor_topic(topic)

        try:
            self.query_one("#user-input", TextArea).focus()
        except NoMatches:
            pass

    async def _restore_topic_messages(self, topic: TopicSession) -> None:
        """Clear the shared #messages container and repopulate with this topic's history.
        
        FIX: Sets _restoring=True so the background monitor does not double-mount
        messages that arrive while we are rebuilding the DOM. Also restores the
        placeholder Static so the container is never completely empty.
        """
        topic._restoring = True
        try:
            msgs = self.query_one("#messages", ScrollableContainer)
            await msgs.query("*").remove()
            # FIX: restore placeholder so container layout never collapses
            await msgs.mount(Static(""))
            for role, data in topic.message_log:
                if role == "user":
                    await msgs.mount(UserMsg(data))
                elif role == "agent":
                    agent_name, blocks = data
                    await msgs.mount(AgentMsg(agent_name, blocks))
            await asyncio.sleep(0)  # yield so layout completes before scrolling
            msgs.scroll_end(animate=False)
        except NoMatches:
            pass
        finally:
            # FIX: always clear the flag, even if an exception occurred
            topic._restoring = False

    async def _restore_mind_messages(self, topic: TopicSession) -> None:
        """Clear and repopulate the mind history for this topic."""
        try:
            mind = self.query_one("#mind-history", ScrollableContainer)
            await mind.query("*").remove()
            await mind.mount(Static(""))
            for agent_name, blocks in topic.mind_log:
                await mind.mount(AgentMsg(agent_name, blocks))
            await asyncio.sleep(0)
            mind.scroll_end(animate=False)
        except NoMatches:
            pass
        finally:
            topic._mind_restoring = False

    def _refresh_topic_row(self, topic: TopicSession) -> None:
        try:
            prev = self.query_one(f"#topic-preview-{topic.local_id}", Label)
            text = topic.last_preview
            if len(text) > 26:
                text = text[:26] + "…"
            prev.update(text)
        except NoMatches:
            pass
        try:
            t = self.query_one(f"#topic-time-{topic.local_id}", Label)
            t.update(topic.time_str)
        except NoMatches:
            pass
        try:
            u = self.query_one(f"#topic-unread-{topic.local_id}", Label)
            if topic.unread:
                u.update(str(topic.unread))
                u.add_class("has-unread")
            else:
                u.update("")
                u.remove_class("has-unread")
        except NoMatches:
            pass

    def _current_topic(self) -> Optional[TopicSession]:
        return self._topic_map.get(self.active_topic_id)

    # ── Tab management ────────────────────────────────────────

    def switch_tab(self, name: str) -> None:
        self.active_tab = name
        topic = self._current_topic()
        if topic:
            topic.active_tab = name

    def _apply_tab(self, pane_id: str) -> None:
        pane_map = {
            "chat-pane":     "chat-pane-box",
            "agent-pane":    "agent-pane-box",
            "terminal-pane": "terminal-pane-box",
        }
        for pid, box_id in pane_map.items():
            try:
                box = self.query_one(f"#{box_id}")
                if pid == pane_id:
                    box.display = True
                    box.add_class("show")
                else:
                    box.display = False
                    box.remove_class("show")
            except NoMatches:
                pass

        for btn in self.query(TabBtn):
            btn.add_class("active") if btn._tabid == pane_id else btn.remove_class("active")

    def watch_active_tab(self, val: str) -> None:
        self._apply_tab(val)
        if val == "chat-pane":
            try:
                self.query_one("#user-input", TextArea).focus()
            except NoMatches:
                pass
        elif val == "terminal-pane":
            try:
                self.query_one("#term-input", Input).focus()
            except NoMatches:
                pass

    # ── SE initialisation ─────────────────────────────────────

    @work(exclusive=True)
    async def init_soulengine(self) -> None:
        log = self._log_term
        log("[dim]--- SoulEngine initialising ---[/dim]")
        try:
            self._se_runtime = GLOBAL_SE_RUNTIME
            log("[#4ade80]runtime created[/#4ade80]")
            self.se_ready = True
            self._set_badge(f"Live: http://{se_bind}", "ok")
            log("[#4ade80]--- SoulEngine ready ---[/#4ade80]")

            if AGENTS:
                try:
                    sel = self.query_one("#agent-select", Select)
                    sel.set_options([(name, name) for name in AGENTS])
                    sel.value = AGENTS[0]
                except NoMatches:
                    pass
        except Exception as e:
            self._set_badge("SE: error", "err")
            log(f"[bold #f87171]SE init error: {e}[/bold #f87171]")

    # ── Per-topic chat monitor ─────────────────────────────────

    @work()
    async def chat_monitor_topic(self, topic: TopicSession) -> None:
        """Background monitor scoped to a single TopicSession.

        FIX 1: cursor arithmetic uses cursor_before + len(new_entries) — the
               old `+ 1` offset caused one message to be skipped every poll cycle.

        FIX 2: checks topic._restoring before mounting to DOM so we never
               double-mount messages that _restore_topic_messages is already
               rebuilding from topic.message_log.
        """
        if not topic.se_topic_id:
            return
        try:
            # FIX 1: initialise local cursor from topic state (correct baseline)
            cursor_before = topic.msg_cursor
            while True:
                await asyncio.sleep(1)
                await self._agent_monitor_topic(topic)

                new_len = await self._se_runtime.topic_history_len(topic.se_topic_id)
                if new_len <= cursor_before:
                    continue

                mem_iter = await self._se_runtime.iter_topic(topic.se_topic_id, cursor_before)
                mem_iter = json.loads(mem_iter)
                new_entries = list(mem_iter)

                # FIX 1: removed the erroneous `+ 1` — advance by exactly the
                # number of entries we received, nothing more.
                topic.msg_cursor = cursor_before + len(new_entries)
                cursor_before = topic.msg_cursor

                if new_entries:
                    for mem in new_entries:
                        if mem['role'] == "user":
                            continue
                        src = mem['name']
                        content = mem['content']
                        blocks = parse_se_content(content)

                        # Always store in topic log regardless of active view
                        topic.message_log.append(("agent", (src, blocks)))

                        topic.last_preview = content[:40]
                        topic.last_msg_time = datetime.now()

                        # FIX 2: only touch the DOM when this topic is active AND
                        # _restore_topic_messages is not currently rebuilding it.
                        # If _restoring is True the message is already in
                        # topic.message_log and will be rendered by the restore.
                        if self.active_topic_id == topic.local_id and not topic._restoring:
                            try:
                                msgs = self.query_one("#messages", ScrollableContainer)
                                await msgs.mount(AgentMsg(src, blocks))
                                await asyncio.sleep(0)  # yield so layout settles
                                msgs.scroll_end(animate=False)
                            except NoMatches:
                                pass
                        elif self.active_topic_id != topic.local_id:
                            topic.unread += 1

                        self._refresh_topic_row(topic)
                        self._log_term(f"[#4ade80]-> {src}: {content[:60]}…[/#4ade80]")

        except Exception as e:
            logging.error(f"Chat Monitor Error (topic {topic.local_id}): {e}")

    async def _agent_monitor_topic(self, topic: TopicSession) -> None:
        try:
            if not topic.se_active_agent_id or not topic.se_topic_id:
                if self.active_topic_id == topic.local_id:
                    self.is_thinking = False
                return
            agent_status = await self._se_runtime.is_agent_working_on_topic(
                topic.se_topic_id, topic.se_active_agent_id
            )
            if self.active_topic_id == topic.local_id:
                self.is_thinking = (agent_status is True)

            new_len = await self._se_runtime.agent_episode_len(
                topic.se_topic_id, topic.se_active_agent_id
            )
            if new_len <= topic.se_active_agent_cursor_before and new_len > 0:
                return

            mem_iter = await self._se_runtime.iter_agent_episode(
                topic.se_topic_id, topic.se_active_agent_id,
                max(0, topic.se_active_agent_cursor_before)
            )
            mem_iter = json.loads(mem_iter)
            new_entries = list(mem_iter)
            if new_entries:
                for mem in new_entries:
                    blocks = parse_se_content(mem['content'])
                    topic.mind_log.append((mem['name'], blocks))
                    if self.active_topic_id == topic.local_id and not topic._mind_restoring:
                        try:
                            mind = self.query_one("#mind-history", ScrollableContainer)
                            await mind.mount(AgentMsg(mem['name'], blocks))
                            mind.scroll_end(animate=False)
                        except NoMatches:
                            pass
            topic.se_active_agent_cursor_before = new_len
        except Exception as e:
            logging.error(f"Agent Monitor Error: {e}")

    async def _add_agent_to_topic_session(self, topic: TopicSession, name: str) -> None:
        if not self.se_ready or name in topic.se_added:
            return
        if name not in topic.se_agent_ids or topic.se_agent_ids.get(name) is None:
            try:
                topic.se_agent_ids[name] = await self._se_runtime.deploy_agent(name)
            except Exception as e:
                self._log_term(f"[#f87171]Deploy agent error: {e}[/#f87171]")

        agent_id = topic.se_agent_ids.get(name)
        if not agent_id:
            return
        try:
            if topic.se_active_agent_id:
                await self._se_runtime.remove_agent_from_topic(
                    topic.se_topic_id, topic.se_active_agent_id
                )
                topic.se_active_agent_cursor_before = -1

            await self._se_runtime.add_agent_to_topic(topic.se_topic_id, agent_id)
            topic.se_active_agent_id = agent_id
            topic.se_active_agent_name = name
            topic.se_added.add(name)

            try:
                self.query_one("#topic-header-status", Label).update(
                    f"agent: {name}  |  {topic.se_topic_id or 'pending'}"
                )
            except NoMatches:
                pass

            self._log_term(f"[dim]agent {name} added to episode {topic.local_id}[/dim]")
        except Exception as e:
            self._log_term(f"[#f87171]add_agent_to_topic error: {e}[/#f87171]")

    # ── Input handling ────────────────────────────────────────

    async def _do_send(self) -> None:
        """Core send logic — called from action_send_message."""
        try:
            ta = self.query_one("#user-input", TextArea)
            text = ta.text.strip()
            if not text:
                return
            ta.clear()

            topic = self._current_topic()
            if not topic:
                return

            topic.message_log.append(("user", text))

            msgs = self.query_one("#messages", ScrollableContainer)
            await msgs.mount(UserMsg(text))
            msgs.scroll_end(animate=False)

            topic.last_preview = text[:40]
            topic.last_msg_time = datetime.now()
            self._refresh_topic_row(topic)

            if self.se_ready and topic.se_topic_id:
                await self._se_send_topic(topic, text, msgs)
            else:
                await self._demo_respond(text, msgs, topic)
        except NoMatches:
            pass

    @on(Select.Changed, "#agent-select")
    def handle_agent_select(self, event: Select.Changed) -> None:
        if event.value and event.value != "—":
            topic = self._current_topic()
            if topic:
                asyncio.create_task(
                    self._add_agent_to_topic_session(topic, str(event.value))
                )

    @on(Button.Pressed, "#new-episode-btn")
    def handle_new_episode_btn(self, event: Button.Pressed) -> None:
        self.action_new_topic()

    @on(Button.Pressed, "#attach-btn")
    def handle_attach_btn(self, event: Button.Pressed) -> None:
        self.action_attach_file()

    @on(Input.Changed, "#topic-search")
    def handle_topic_search(self, event: Input.Changed) -> None:
        query = event.value.lower()
        for row in self.query(TopicRow):
            if row._topic.name.lower() == query:
                row.display = True
            else:
                row.display = not query or query in row._topic.name.lower()

    async def _se_send_topic(self, topic: TopicSession, text: str, msgs: ScrollableContainer) -> None:
        if not topic.se_active_agent_id:
            agent_name = AGENTS[0] if AGENTS else None
            if agent_name:
                await self._add_agent_to_topic_session(topic, agent_name)
        try:
            await self._se_runtime.insert_message(topic.se_topic_id, topic.se_user_id, text)
        except Exception as e:
            self._log_term(f"[#f87171]SE send error: {e}[/#f87171]")
            blocks = [("output", f"Error: {e}")]
            topic.message_log.append(("agent", ("error", blocks)))
            await msgs.mount(AgentMsg("error", blocks))
            msgs.scroll_end(animate=False)

    async def _demo_respond(self, text: str, msgs: ScrollableContainer, topic: TopicSession) -> None:
        blocks = [
            ("thought", f"Parsing: \"{text[:55]}{'...' if len(text) > 55 else ''}\""),
            ("output",  "Demo mode — SoulEngine not loaded."),
        ]
        topic.message_log.append(("agent", ("demo", blocks)))
        await msgs.mount(AgentMsg("demo", blocks))
        msgs.scroll_end(animate=False)

    # ── Thinking indicator ────────────────────────────────────

    def watch_is_thinking(self, val: bool) -> None:
        try:
            t = self.query_one("#thinking")
            t.add_class("show") if val else t.remove_class("show")
        except NoMatches:
            pass

    # ── Terminal ──────────────────────────────────────────────

    def _seed_terminal_header(self) -> None:
        self._log_term(f"[dim]--- Kattalai shell  {datetime.now().strftime('%Y-%m-%d %H:%M')} ---[/dim]")
        self._log_term(f"[dim]SoulEngine: {'YES' if SE_AVAILABLE else 'NO (demo)'}[/dim]")
        self._log_term("[dim]Ctrl+N = new episode  |  type 'help' for commands[/dim]")

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

        if verb == "topics":
            for t in self._topics:
                active = "●" if t.local_id == self.active_topic_id else "○"
                log.write(f"  {active} [{t.local_id}] {t.name:20s}  msgs={t.msg_cursor}  agent={t.se_active_agent_name or '—'}")

        elif verb == "se.status":
            topic = self._current_topic()
            if self.se_ready and topic:
                log.write(f"[#4ade80]episode '{topic.name}' (id={topic.local_id})[/#4ade80]")
                log.write(f"  se_topic_id  = {topic.se_topic_id}")
                log.write(f"  se_user_id   = {topic.se_user_id}")
                log.write(f"  active_agent = {topic.se_active_agent_name}")
                log.write(f"  added        = {list(topic.se_added)}")
                log.write(f"  msg_log_len  = {len(topic.message_log)}")
                log.write(f"  restoring    = {topic._restoring}")
            else:
                log.write("[#f59e0b]SE not ready or no active episode[/#f59e0b]")

        elif verb == "help":
            log.write("[#60a5fa]App:[/#60a5fa]")
            log.write("  topics             — list all episodes")
            log.write("  se.status          — active episode SE info")
            log.write("  clear              — clear terminal")
            log.write("[#60a5fa]Keys:[/#60a5fa]")
            log.write("  Ctrl+N  new episode")
            log.write("  Ctrl+↑/↓  navigate episodes")
            log.write("  Ctrl+1/2/3  switch tabs")

        elif verb == "clear":
            log.clear()
            log.write("[dim]--- cleared ---[/dim]")

        else:
            log.write(f"[#f87171]unknown: '{cmd}'  (try 'help')[/#f87171]")

    # ── Helpers ───────────────────────────────────────────────

    def _set_badge(self, text: str, level: str = "ok") -> None:
        try:
            b = self.query_one("#se-badge", Label)
            b.update(text)
        except NoMatches:
            pass

    # ── Actions ───────────────────────────────────────────────

    def action_new_topic(self) -> None:
        async def _open() -> None:
            def _on_dismiss(name: Optional[str]) -> None:
                if not name:
                    return
                asyncio.create_task(self._create_topic(name))
            await self.push_screen(NewTopicModal(), callback=_on_dismiss)
        asyncio.create_task(_open())

    async def action_clear(self) -> None:
        if self.active_tab == "chat-pane":
            topic = self._current_topic()
            if topic:
                topic.message_log.clear()
            msgs = self.query_one("#messages", ScrollableContainer)
            await msgs.query("*").remove()
            await msgs.mount(Static(""))
        elif self.active_tab == "terminal-pane":
            log = self.query_one("#term-log", RichLog)
            log.clear()
            log.write("[dim]--- cleared ---[/dim]")

    def action_tab_chat(self)     -> None: self.switch_tab("chat-pane")
    def action_tab_mind(self)     -> None: self.switch_tab("agent-pane")
    def action_tab_terminal(self) -> None: self.switch_tab("terminal-pane")

    def action_focus_input(self) -> None:
        try:
            if self.active_tab == "terminal-pane":
                self.query_one("#term-input", Input).focus()
            else:
                self.query_one("#user-input", TextArea).focus()
        except NoMatches:
            pass

    def action_prev_topic(self) -> None:
        if not self._topics:
            return
        idx = next((i for i, t in enumerate(self._topics) if t.local_id == self.active_topic_id), -1)
        if idx > 0:
            self.switch_topic(self._topics[idx - 1].local_id)

    def action_next_topic(self) -> None:
        if not self._topics:
            return
        idx = next((i for i, t in enumerate(self._topics) if t.local_id == self.active_topic_id), -1)
        if idx < len(self._topics) - 1:
            self.switch_topic(self._topics[idx + 1].local_id)

    def action_send_message(self) -> None:
        asyncio.create_task(self._do_send())

    def action_attach_file(self) -> None:
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
    print("Downloading assets from GitHub…")
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
    print("Upgrading kattalai package…")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "kattalai"], check=True)
    print("  ✓ Package upgraded")
    for folder in folders:
        dst = base / folder
        if dst.exists():
            shutil.rmtree(dst)
            print(f"  ✓ Removed {folder}")
    print("Downloading fresh assets from GitHub…")
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
    zip_path.unlink()
    shutil.rmtree(base / "temp_extract")
    print("Upgrade complete.")


def main():
    os.chdir(Path(__file__).parent)
    setup()
    asyncio.run(load_run_time())
    KattalaiApp().run()


if __name__ == "__main__":
    main()