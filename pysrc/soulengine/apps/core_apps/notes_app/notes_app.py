import json
import sys
import shutil
import re
from datetime import datetime

from pathlib import Path
# .parent is 'myapp', .parent.parent is 'apps'
apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
NOTES_FILE  = os.path.join(BASE_DIR , "notes.json")
BACKUP_DIR  = os.path.join(BASE_DIR , "notes_backups")

# ── Storage helpers ───────────────────────────────────────────────────────────

def ensure_dirs():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def load_notes() -> list[dict]:
    ensure_dirs()
    if not NOTES_FILE.exists():
        return []
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []

def save_notes(notes: list[dict]):
    NOTES_FILE.write_text(
        json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
    )

def next_id(notes: list[dict]) -> int:
    return max((n.get("id", 0) for n in notes), default=0) + 1

def extract_tags(text: str) -> tuple[list[str], str]:
    """Pull #tags out of text, return (tags, clean_text)."""
    tags = [w[1:] for w in text.split() if w.startswith("#") and len(w) > 1]
    clean = re.sub(r"\s?#\w+", "", text).strip()
    return tags, clean or text

# ── Command handlers ──────────────────────────────────────────────────────────

def handle_add(args: list[str]) -> dict:
    text = " ".join(args).strip()
    if not text:
        return {"status": "error", "message": "No note text provided."}

    tags, clean_text = extract_tags(text)
    notes = load_notes()
    note = {
        "id":        next_id(notes),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "text":      clean_text,
        "tags":      tags,
    }
    notes.append(note)
    save_notes(notes)
    return {"status": "saved", "note": note}


def handle_read(args: list[str]) -> dict:
    notes = load_notes()

    # --tag filter
    if "--tag" in args:
        idx = args.index("--tag")
        tag = args[idx + 1].lstrip("#") if idx + 1 < len(args) else ""
        notes = [n for n in notes if tag in n.get("tags", [])]
        return {"status": "ok", "filter": f"tag:{tag}", "count": len(notes), "notes": notes}

    # last-N filter
    numeric = [a for a in args if a.isdigit()]
    if numeric:
        limit = int(numeric[0])
        notes = notes[-limit:]

    return {"status": "ok", "count": len(notes), "notes": notes}


def handle_search(args: list[str]) -> dict:
    query = " ".join(args).lower().strip()
    if not query:
        return {"status": "error", "message": "No search query provided."}

    notes = load_notes()
    matches = [
        n for n in notes
        if query in n.get("text", "").lower()
        or query in " ".join(n.get("tags", [])).lower()
    ]
    return {"status": "ok", "query": query, "count": len(matches), "notes": matches}


def handle_update(args: list[str]) -> dict:
    if len(args) < 2 or not args[0].isdigit():
        return {"status": "error", "message": "Usage: update <id> <new text>"}

    nid      = int(args[0])
    new_text = " ".join(args[1:]).strip()
    notes    = load_notes()

    for note in notes:
        if note.get("id") == nid:
            tags, clean = extract_tags(new_text)
            old_text       = note["text"]
            note["text"]   = clean
            note["tags"]   = tags
            note["edited_at"] = datetime.now().isoformat(timespec="seconds")
            save_notes(notes)
            return {"status": "updated", "id": nid, "old_text": old_text, "new_text": clean}

    return {"status": "error", "message": f"Note #{nid} not found."}


def handle_delete(args: list[str]) -> dict:
    if not args or not args[0].isdigit():
        return {"status": "error", "message": "Usage: delete <id>"}

    nid    = int(args[0])
    notes  = load_notes()
    target = next((n for n in notes if n.get("id") == nid), None)

    if not target:
        return {"status": "error", "message": f"Note #{nid} not found."}

    notes = [n for n in notes if n.get("id") != nid]
    save_notes(notes)
    return {"status": "deleted", "note": target}


def handle_backup(args: list[str]) -> dict:
    # backup list
    if args and args[0] == "list":
        backups = sorted(BACKUP_DIR.glob("*.json"), reverse=True)
        return {
            "status":  "ok",
            "backups": [{"name": b.name, "size_bytes": b.stat().st_size} for b in backups],
        }

    notes = load_notes()
    if not notes:
        return {"status": "error", "message": "No notes to backup."}

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"notes_backup_{ts}.json"
    shutil.copy2(NOTES_FILE, dest)
    return {"status": "backup_created", "file": str(dest), "notes_count": len(notes)}


def handle_restore(args: list[str]) -> dict:
    if not args:
        return {"status": "error", "message": "Usage: restore <backup_filename>"}

    src = Path(args[0]) if Path(args[0]).is_absolute() else BACKUP_DIR / args[0]
    if not src.exists():
        return {"status": "error", "message": f"Backup not found: {src}"}

    # auto-backup current before overwriting
    if NOTES_FILE.exists():
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre = BACKUP_DIR / f"notes_pre_restore_{ts}.json"
        shutil.copy2(NOTES_FILE, pre)

    shutil.copy2(src, NOTES_FILE)
    notes = load_notes()
    return {"status": "restored", "source": src.name, "notes_count": len(notes)}


def handle_clear(args: list[str]) -> dict:
    notes = load_notes()
    if not notes:
        return {"status": "already_empty"}

    # auto-backup before clearing
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"notes_pre_clear_{ts}.json"
    if NOTES_FILE.exists():
        shutil.copy2(NOTES_FILE, dest)

    save_notes([])
    return {
        "status":       "cleared",
        "deleted_count": len(notes),
        "auto_backup":  dest.name,
    }


def handle_stats(args: list[str]) -> dict:
    notes   = load_notes()
    backups = list(BACKUP_DIR.glob("*.json"))

    all_tags: dict[str, int] = {}
    for note in notes:
        for tag in note.get("tags", []):
            all_tags[tag] = all_tags.get(tag, 0) + 1

    return {
        "status":        "ok",
        "total_notes":   len(notes),
        "total_words":   sum(len(n.get("text", "").split()) for n in notes),
        "edited_notes":  sum(1 for n in notes if n.get("edited_at")),
        "total_backups": len(backups),
        "oldest_note":   notes[0].get("timestamp", "")[:10] if notes else None,
        "newest_note":   notes[-1].get("timestamp", "")[:10] if notes else None,
        "top_tags":      sorted(all_tags.items(), key=lambda x: -x[1])[:5],
    }


# ── Command router ────────────────────────────────────────────────────────────

COMMANDS = {
    "read":    handle_read,
    "search":  handle_search,
    "update":  handle_update,
    "delete":  handle_delete,
    "backup":  handle_backup,
    "restore": handle_restore,
    "clear":   handle_clear,
    "stats":   handle_stats,
}

async def process_command(se_interface, args):
    if not args:
        se_interface.send_message(json.dumps({
            "status": "error",
            "message": "No command or note provided.",
            "usage": "notes_app <text> | read | search <q> | update <id> <text> | delete <id> | backup | restore <file> | clear | stats",
        }))
        return

    cmd = args[0].lower()

    if cmd in COMMANDS:
        result = COMMANDS[cmd](args[1:])
    else:
        # treat entire args as a new note
        result = handle_add(args)

    se_interface.send_message(json.dumps(result, ensure_ascii=False))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    soul_app = soul_engine_app(app_name="SOUL NOTE TAKER")
    soul_app.run_one_shot(main_fn=process_command)