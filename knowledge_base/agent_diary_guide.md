# Agent Diary — Usage Guide

> Rules for how the agent reads and writes its own diary. This is the agent's long-term memory protocol.

## What the Diary Is For

The agent has no memory between sessions by default. Every conversation starts blank.
The diary exists to fix this — it is a persistent markdown file the agent reads at session
start and writes to as it learns things worth keeping.

**The diary is not a conversation transcript.**
It is distilled, structured memory — the kind of thing a person would write in a notebook
after a meeting, not a recording of everything said.

---

## When to Read the Diary

**Read `agent_diary.md` at the very start of every session**, before responding to the user's
first message. This is non-negotiable — without reading it, the agent is starting blind.

```
&codex_app read path=./knowledge_base/agent_diary.md
```

Use the content to:
- Recall who the user is and how they prefer to communicate
- Pick up any ongoing tasks or open threads
- Remember constraints or preferences established in previous sessions
- Avoid repeating mistakes already logged

---

## When to Write to the Diary

Write **during or at the end of a session** when any of the following happen:

| Trigger | What to write | Where |
|---------|--------------|-------|
| User states a preference explicitly | The preference, verbatim or paraphrased | Persistent Preferences |
| A multi-session task begins | Task name, current status, next step | Ongoing Context |
| A multi-session task completes | Mark it done or remove it | Ongoing Context |
| Something non-obvious is discovered about the workspace | What was found and where | Workspace Notes |
| User corrects the agent | What went wrong, what is correct | Mistakes and Corrections |
| A one-off fact is established (name, timezone, project name) | The fact | User Profile or Things to Remember |
| Session ends | One-line summary of what was done | Session Log |

**Do not write** for things that are only relevant to this session.
If it won't matter next time, it doesn't belong in the diary.

---

## How to Write — Commands

### Append a new entry to a section
For adding to Preferences, Things to Remember, Workspace Notes, Mistakes, Session Log:
```
&codex_app append path=./knowledge_base/agent_diary.md
  content="\n### Persistent Preferences\n- Prefers bullet points over prose in technical answers. (2026-04-25)"
```

### Update a section (e.g. User Profile, Ongoing Context)
Read the full file first, make the targeted change to that section's content,
then write back the whole file:
```
&codex_app read path=./knowledge_base/agent_diary.md
→ compose updated content with the section changed
&codex_app edit path=./knowledge_base/agent_diary.md content="<full updated file>"
```

**Never use edit to overwrite the file with just the changed section** — always
preserve all other sections intact.

---

## What Good Diary Entries Look Like

### User Profile — good
```
- **Name:** Raja
- **Location:** Chennai, India
- **Technical level:** Advanced — comfortable with Rust, Python, systems design
- **Communication style:** Terse; prefers direct answers over explanations
- **Recurring projects:** Kattalai agent runtime (github.com/RajaGanapathyM/kattalai)
```

### Persistent Preferences — good entries
```
- Prefers code over prose explanations when both would work. (2026-04-25)
- Uses Tanglish (Tamil-English) in casual messages — respond naturally to this, no need to note it. (2026-04-25)
- Does not want unsolicited suggestions about alternative approaches unless asked. (2026-04-26)
```

### Ongoing Context — good entry
```
**Codex App integration** (started 2026-04-25)
- Status: app built, TOML and py delivered
- Next: seed the knowledge base with app guides
- Blocker: none
```

### Mistakes and Corrections — good entry
```
- 2026-04-25: Tried to write files inside ./knowledge_base using file_handler_app.
  Correct approach: always use codex_app for anything inside ./knowledge_base.
```

### Session Log — good entry
```
2026-04-25 | Built codex_app (TOML + py), wrote knowledge base guides for codex_app and computer use, created agent_diary.md
```

---

## What NOT to Put in the Diary

- Full conversation transcripts — too long, hard to use
- Things the user said in passing that were not preferences or facts
- Sensitive information (passwords, keys, personal data beyond name/location)
- Speculation about the user's intent
- Duplicate entries — check the existing section before appending

---

## Diary Maintenance

If the diary grows too long (over ~300 lines), consolidate:
- Merge redundant preference entries
- Archive completed ongoing tasks (delete them from Ongoing Context)
- Keep the Session Log to the last 20 sessions

The diary must remain **fast to read** — it is loaded at session start.
A bloated diary defeats its own purpose.

---

## Example — Full Session Flow

```
Session starts
│
├── &codex_app read path=./knowledge_base/agent_diary.md
│    → agent now knows: user is Raja, prefers terse answers,
│      has an ongoing Kattalai project, last session built codex_app
│
├── [conversation happens]
│    → user mentions: "I always use --break-system-packages with pip"
│    → this is a preference worth keeping
│
├── End of session:
│    &codex_app append path=./knowledge_base/agent_diary.md
│      content="\n- Always use --break-system-packages flag with pip install. (2026-04-25)"
│      (under Persistent Preferences)
│
│    &codex_app append path=./knowledge_base/agent_diary.md
│      content="\n2026-04-25 | Created computer_use_guide.md and agent_diary.md"
│      (under Session Log)
│
└── Session ends
```

---

## Related

- [Codex App Guide](./codex_app_guide.md)
- [Computer Use Guide](./computer_use_guide.md)