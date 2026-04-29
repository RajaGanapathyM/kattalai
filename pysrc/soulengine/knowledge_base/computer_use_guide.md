# Computer Use — Agent Guide for General Tasks

> How the agent should use shell_app, file_handler_app, and system tools to accomplish real user tasks safely and effectively.

## Mental Model

The agent has access to the user's computer through two primary apps:

| App | Handle | Purpose |
|-----|--------|---------|
| `shell_app` | `&shell_app` | Run commands, scripts, query the environment |
| `file_handler_app` | `&file_handler_app` | Create, read, edit, move, delete files and folders |

**Shell app = doing things. File handler = managing things.**

Both apps show a GUI permission dialog before any destructive or mutating
operation. The agent must never attempt to work around this — the dialog
is the user's control surface. If the user denies, stop and report.

**Never chain a destructive command directly after a read without confirming
the result looks correct first.** Read → verify → then mutate.

---

## shell_app — Command Reference

### run — Execute a shell command
```
&shell_app run cmd="ls -lah ./src"
&shell_app run cmd="python3 script.py --input data.csv"
&shell_app run cmd="pip install pandas --break-system-packages"
&shell_app run cmd="cat ./config.json"
&shell_app run cmd="echo $HOME"
```

### script — Run a multi-line script
```
&shell_app script code="#!/bin/bash
cd ./project
git pull origin main
pip install -r requirements.txt
echo 'done'"
```
Use `script` when the task requires multiple commands in sequence with shared
shell state (same working directory, same environment variables).

### which — Check if a tool is installed
```
&shell_app which tool="ffmpeg"
&shell_app which tool="node"
&shell_app which tool="git"
```
Always run `which` before attempting to use an external tool — fail fast
with a clear "not installed" message rather than a cryptic runtime error.

### env — Read environment variables
```
&shell_app env var="PATH"
&shell_app env var="PYTHONPATH"
&shell_app env var="HOME"
```

### kill — Terminate a running process
```
&shell_app kill pid=3821
```
Requires user permission. Always confirm the PID is correct via
`run cmd="ps aux | grep <name>"` before killing.

---

## file_handler_app — Command Reference

### list — Browse a directory
```
&file_handler_app list path=./src
&file_handler_app list path=glob:**/*.py
```

### stat — Inspect a file
```
&file_handler_app stat path=./config.toml
```
Returns size, created_at, modified_at, permissions. Useful before editing.

### search — Find text inside files
```
&file_handler_app search path=./src pattern="def process_command"
&file_handler_app search path=. pattern="TODO"
```

### new — Create a file
```
&file_handler_app new path=./scripts/setup.sh content="#!/bin/bash\necho hello"
```

### edit — Overwrite a file
```
&file_handler_app edit path=./config.json content='{"debug": true}'
```

### append — Add to a file
```
&file_handler_app append path=./logs/run.log content="[2026-04-25] run complete"
```

### copy / move / rename / delete / rmdir
```
&file_handler_app copy src=./a.py dest=./backup/a.py
&file_handler_app move src=./draft.md dest=./final/draft.md
&file_handler_app rename path=./old.py new_name=new.py
&file_handler_app delete path=./temp/scratch.py
&file_handler_app rmdir path=./temp recursive=true
```

---

## Decision Tree — Which App for What

```
User wants to...
│
├── Read a file's content?
│     → shell_app run cmd="cat ./file"        (quick, any format)
│     → file_handler_app stat path=./file     (metadata only)
│
├── List what's in a folder?
│     → file_handler_app list path=./folder
│
├── Find files by name?
│     → shell_app run cmd="find . -name '*.log'"
│
├── Find text inside files?
│     → file_handler_app search path=. pattern="keyword"
│     → shell_app run cmd="grep -rn 'keyword' ./src"
│
├── Run a program or command?
│     → shell_app run cmd="..."
│
├── Create or overwrite a file?
│     → file_handler_app new / edit
│
├── Check if something is installed?
│     → shell_app which tool="..."
│
├── Monitor system resources?
│     → shell_app run cmd="free -h"   (RAM)
│     → shell_app run cmd="df -h"     (disk)
│     → shell_app run cmd="uptime"    (load)
│
└── Kill a process?
      → shell_app run cmd="ps aux | grep name"   (find PID first)
      → shell_app kill pid=...
```

---

## Common Task Scenarios

### Scenario 1 — "Run my Python script"
```
Step 1: &shell_app which tool="python3"
         → confirm Python is available

Step 2: &file_handler_app stat path=./script.py
         → confirm file exists

Step 3: &shell_app run cmd="python3 ./script.py"
         → execute; show output to user
```
If the script takes arguments: `cmd="python3 ./script.py --arg value"`  
If the script needs a specific working directory: use `script` with a `cd` first.

---

### Scenario 2 — "Install this Python package"
```
Step 1: &shell_app which tool="pip3"

Step 2: &shell_app run cmd="pip3 show pandas"
         → check if already installed before installing

Step 3 (if not installed):
        &shell_app run cmd="pip3 install pandas --break-system-packages"
        → show install output to user
```
Always check before installing — avoids redundant installs and surfacing
version conflict errors unnecessarily.

---

### Scenario 3 — "Show me what's in this folder"
```
&file_handler_app list path=./project
```
If the user wants recursive listing including subfolders:
```
&shell_app run cmd="find ./project -type f | sort"
```
If the user wants sizes:
```
&shell_app run cmd="du -sh ./project/* | sort -h"
```

---

### Scenario 4 — "Find all TODO comments in the codebase"
```
&file_handler_app search path=./src pattern="TODO"
```
Returns each match with filename, line number, and the line itself.
Group by file for clarity when presenting to the user.

---

### Scenario 5 — "Create a shell script and make it executable"
```
Step 1: &file_handler_app new path=./scripts/deploy.sh
         content="#!/bin/bash\nset -e\necho 'deploying...'"

Step 2: &shell_app run cmd="chmod +x ./scripts/deploy.sh"

Step 3 (optional test):
        &shell_app run cmd="./scripts/deploy.sh"
```

---

### Scenario 6 — "Check if a port is in use"
```
&shell_app run cmd="ss -tulnp | grep :8080"
```
If nothing returns, port is free. If a line returns, show the process
name and PID to the user and ask what they want to do.

---

### Scenario 7 — "Back up this folder before I edit it"
```
Step 1: &shell_app run cmd="date +%Y%m%d_%H%M%S"
         → get timestamp for backup name

Step 2: &file_handler_app copy src=./config dest=./config_backup_20260425_1032
         → user approves in dialog
```

---

### Scenario 8 — "How much disk space am I using?"
```
&shell_app run cmd="df -h"          → all mounted filesystems
&shell_app run cmd="du -sh ./*"     → top-level folder sizes in cwd
&shell_app run cmd="du -sh ~/.* | sort -h"   → hidden home folder sizes
```
Pick the right scope based on what the user is asking about.

---

### Scenario 9 — "Rename all .txt files to .md in this folder"
```
Step 1: &shell_app run cmd="find ./notes -name '*.txt' | head -20"
         → preview which files will be affected; show user

Step 2: Confirm with user before bulk rename

Step 3: &shell_app script code="for f in ./notes/*.txt; do
  mv \"$f\" \"${f%.txt}.md\"
done
echo 'done'"
```
Always preview bulk operations before executing. Show count and sample
filenames — never run a bulk rename blind.

---

### Scenario 10 — "What processes are using the most memory?"
```
&shell_app run cmd="ps aux --sort=-%mem | head -15"
```

---

### Scenario 11 — "Edit a config file"
```
Step 1: &shell_app run cmd="cat ./config.toml"
         → read current content; display to user

Step 2: User provides the change

Step 3: Compose full updated content

Step 4: &file_handler_app edit path=./config.toml content="<full updated content>"
         → user approves in dialog
```
Never edit a config file without reading it first.
Never do a partial edit — always pass the complete new content to `edit`.
Use `append` only for log files or clearly additive changes.

---

### Scenario 12 — "Check if my service is running"
```
&shell_app run cmd="systemctl status myservice"
```
Or for a non-systemd process:
```
&shell_app run cmd="ps aux | grep myservice | grep -v grep"
```

---

### Scenario 13 — "Run a git operation"
```
# Check status
&shell_app run cmd="git -C ./project status"

# Pull latest
&shell_app run cmd="git -C ./project pull origin main"

# Show recent commits
&shell_app run cmd="git -C ./project log --oneline -10"

# Check what changed in a file
&shell_app run cmd="git -C ./project diff HEAD -- ./src/main.py"
```
Always use `-C <path>` to explicitly set the repo directory rather than
relying on working directory state.

---

### Scenario 14 — "Download a file from the internet"
```
Step 1: &shell_app which tool="curl"
         (fallback: &shell_app which tool="wget")

Step 2: &shell_app run cmd="curl -L -o ./downloads/file.zip https://example.com/file.zip"
```

---

### Scenario 15 — "Find a file I can't locate"
```
# By name
&shell_app run cmd="find ~ -name 'report.pdf' 2>/dev/null"

# By partial name
&shell_app run cmd="find ~ -iname '*report*' 2>/dev/null | head -20"

# Modified recently
&shell_app run cmd="find ~/Documents -mtime -3 -type f | sort"
```
Scope the search to a reasonable directory (`~`, `./project`) — never
`find /` unless the user explicitly asks, as it scans the entire filesystem.

---

## Best Practices

### Read Before You Write
Before editing any file, read its current content with
`shell_app run cmd="cat ./file"` or `file_handler_app stat`.
This prevents overwriting something the user cares about and gives
you the full picture before making changes.

### Preview Before Bulk Operations
Any task that will affect multiple files — renaming, deleting, moving —
must be previewed first. Show the user the list of affected files and
confirm before running. Bulk operations are hard to undo.

### Prefer Specific Paths Over Wildcards
`rm ./logs/run.log` is recoverable from a mistake.
`rm ./logs/*.log` is not. When constructing commands with wildcards,
always echo or list the expanded set first.

### Capture Output Before Acting On It
When a command's output drives the next action (e.g., grep for a PID,
then kill), always show the intermediate output to the user before
executing the consequential step. Never chain blindly.

### Respect Permission Denials
If the user denies a permission dialog, do not retry the same operation.
Report that the operation was cancelled and ask what the user wants to do instead.
Under no circumstances should the agent try to accomplish the same mutation
via a different app or a raw shell trick.

### Handle Missing Tools Gracefully
If `which` returns not found, tell the user clearly:
> "ffmpeg is not installed on this system. Would you like me to
> install it, or is there another way you'd like to approach this?"
Never assume a tool is available without checking first.

### Keep Commands Readable
When building shell commands with variables or substitutions, prefer
explicit quoting. A command that is hard for a human to read is hard
to audit for safety.

### Don't Guess at Paths
If you are not certain of a path, use `file_handler_app list` or
`shell_app run cmd="find . -name '...'"` to locate it first.
Writing to the wrong path because of a guess is a common and avoidable error.

### Scope Searches Reasonably
`grep -r` and `find` without a scoped path will scan everything.
Start with the most specific directory that makes sense and broaden only
if the initial scope returns no results.

---

## Error Patterns and Fixes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `command not found` | Tool not installed or not on PATH | Run `which`; check `env var="PATH"` |
| `Permission denied` on file | Wrong ownership or missing execute bit | `stat` the file; `chmod` or `chown` via shell |
| `No such file or directory` | Wrong path | `list` the parent directory to find correct name |
| Script exits non-zero silently | Error output on stderr | Re-run with `2>&1` to capture stderr: `cmd="script.sh 2>&1"` |
| Process won't die with `kill` | Process ignoring SIGTERM | Use `shell_app kill` which sends SIGKILL, or `run cmd="kill -9 <pid>"` |
| Disk full error | Filesystem at 100% | `run cmd="df -h"` and `run cmd="du -sh ./* \| sort -rh \| head -20"` to find large dirs |
| Import error in Python script | Package not installed | `run cmd="pip3 show <package>"` then install |
| Git operation fails | Dirty working tree or merge conflict | `run cmd="git status"` first |

---

## Safety Boundaries

The agent must never:
- Run commands that exfiltrate data to external services without explicit user instruction
- Execute scripts downloaded from the internet without showing the content to the user first
- Use `rm -rf` on any path that is not clearly temporary or explicitly confirmed
- Modify system files outside the user's home and project directories
- Run a background process (`&` or `nohup`) without telling the user it is running in the background

When in doubt about the impact of a command — ask before running.
A one-line confirmation costs nothing. An accidental deletion costs everything.

## Related

- [Codex App Guide](./codex_app_guide.md)