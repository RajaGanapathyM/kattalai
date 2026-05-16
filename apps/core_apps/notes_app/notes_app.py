import json
import sys
import shutil
import re
import os
from datetime import datetime
from pathlib import Path

apps_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(apps_path))
import se_app_utils
from se_app_utils.soulengine import soul_engine_app


class NotesApp(soul_engine_app):
    def __init__(self):
        super().__init__(app_name="SOUL NOTE TAKER")

        script_directory = Path(__file__).parent
        self._notes_file = script_directory / "notes.json"
        self._backup_dir = script_directory / "notes_backups"

        self._commands = {
            "read":    self._handle_read,
            "search":  self._handle_search,
            "update":  self._handle_update,
            "delete":  self._handle_delete,
            "backup":  self._handle_backup,
            "restore": self._handle_restore,
            "clear":   self._handle_clear,
            "stats":   self._handle_stats,
        }

    # ------------------------------------------------------------------ storage
    def _ensure_dirs(self):
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_notes(self) -> list:
        self._ensure_dirs()
        if not self._notes_file.exists():
            return []
        try:
            return json.loads(self._notes_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return []

    def _save_notes(self, notes: list):
        self._notes_file.write_text(
            json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _next_id(self, notes: list) -> int:
        return max((n.get("id", 0) for n in notes), default=0) + 1

    def _extract_tags(self, text: str):
        tags = [w[1:] for w in text.split() if w.startswith("#") and len(w) > 1]
        clean = re.sub(r"\s?#\w+", "", text).strip()
        return tags, clean or text

    # ------------------------------------------------------------------ handlers
    def _handle_add(self, args: list) -> dict:
        text = " ".join(args).strip()
        if not text:
            return {"status": "error", "message": "No note text provided."}
        tags, clean_text = self._extract_tags(text)
        notes = self._load_notes()
        note = {
            "id":        self._next_id(notes),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "text":      clean_text,
            "tags":      tags,
        }
        notes.append(note)
        self._save_notes(notes)
        return {"status": "saved", "note": note}

    def _handle_read(self, args: list) -> dict:
        notes = self._load_notes()
        if "--tag" in args:
            idx  = args.index("--tag")
            tag  = args[idx + 1].lstrip("#") if idx + 1 < len(args) else ""
            notes = [n for n in notes if tag in n.get("tags", [])]
            return {"status": "ok", "filter": f"tag:{tag}", "count": len(notes), "notes": notes}
        numeric = [a for a in args if a.isdigit()]
        if numeric:
            notes = notes[-int(numeric[0]):]
        return {"status": "ok", "count": len(notes), "notes": notes}

    def _handle_search(self, args: list) -> dict:
        query = " ".join(args).lower().strip()
        if not query:
            return {"status": "error", "message": "No search query provided."}
        notes = self._load_notes()
        matches = [
            n for n in notes
            if query in n.get("text", "").lower()
            or query in " ".join(n.get("tags", [])).lower()
        ]
        return {"status": "ok", "query": query, "count": len(matches), "notes": matches}

    def _handle_update(self, args: list) -> dict:
        if len(args) < 2 or not args[0].isdigit():
            return {"status": "error", "message": "Usage: update <id> <new text>"}
        nid      = int(args[0])
        new_text = " ".join(args[1:]).strip()
        notes    = self._load_notes()
        for note in notes:
            if note.get("id") == nid:
                tags, clean       = self._extract_tags(new_text)
                old_text          = note["text"]
                note["text"]      = clean
                note["tags"]      = tags
                note["edited_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_notes(notes)
                return {"status": "updated", "id": nid, "old_text": old_text, "new_text": clean}
        return {"status": "error", "message": f"Note #{nid} not found."}

    def _handle_delete(self, args: list) -> dict:
        if not args or not args[0].isdigit():
            return {"status": "error", "message": "Usage: delete <id>"}
        nid    = int(args[0])
        notes  = self._load_notes()
        target = next((n for n in notes if n.get("id") == nid), None)
        if not target:
            return {"status": "error", "message": f"Note #{nid} not found."}
        self._save_notes([n for n in notes if n.get("id") != nid])
        return {"status": "deleted", "note": target}

    def _handle_backup(self, args: list) -> dict:
        if args and args[0] == "list":
            backups = sorted(self._backup_dir.glob("*.json"), reverse=True)
            return {
                "status":  "ok",
                "backups": [{"name": b.name, "size_bytes": b.stat().st_size} for b in backups],
            }
        notes = self._load_notes()
        if not notes:
            return {"status": "error", "message": "No notes to backup."}
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self._backup_dir / f"notes_backup_{ts}.json"
        shutil.copy2(self._notes_file, dest)
        return {"status": "backup_created", "file": str(dest), "notes_count": len(notes)}

    def _handle_restore(self, args: list) -> dict:
        if not args:
            return {"status": "error", "message": "Usage: restore <backup_filename>"}
        src = Path(args[0]) if Path(args[0]).is_absolute() else self._backup_dir / args[0]
        if not src.exists():
            return {"status": "error", "message": f"Backup not found: {src}"}
        if self._notes_file.exists():
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(self._notes_file, self._backup_dir / f"notes_pre_restore_{ts}.json")
        shutil.copy2(src, self._notes_file)
        return {"status": "restored", "source": src.name, "notes_count": len(self._load_notes())}

    def _handle_clear(self, args: list) -> dict:
        notes = self._load_notes()
        if not notes:
            return {"status": "already_empty"}
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self._backup_dir / f"notes_pre_clear_{ts}.json"
        if self._notes_file.exists():
            shutil.copy2(self._notes_file, dest)
        self._save_notes([])
        return {"status": "cleared", "deleted_count": len(notes), "auto_backup": dest.name}

    def _handle_stats(self, args: list) -> dict:
        notes   = self._load_notes()
        backups = list(self._backup_dir.glob("*.json"))
        all_tags: dict = {}
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

    # ------------------------------------------------------------------ main entry
    async def process_command(self, se_interface, args):
        if not args:
            se_interface.send_message(json.dumps({
                "status":  "error",
                "message": "No command or note provided.",
                "usage":   (
                    "notes_app <text> | read | search <q> | "
                    "update <id> <text> | delete <id> | "
                    "backup | restore <file> | clear | stats"
                ),
            }))
            return

        cmd = args[0].lower()
        if cmd in self._commands:
            result = self._commands[cmd](args[1:])
        else:
            result = self._handle_add(args)

        se_interface.send_message(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    app = NotesApp()
    app.run_one_shot()