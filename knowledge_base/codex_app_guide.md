# Codex App — Agent Usage Guide

> Complete reference for when, why, and how to invoke codex_app to manage the knowledge base.

## What is Codex App?

Codex App is the knowledge-base manager for the `./knowledge_base` directory.
It maintains a tree of Markdown (`.md`) documents organised into topic folders,
and auto-manages an `index.md` table of contents that is rebuilt on every
create, delete, or move operation.

**The agent should treat `codex_app` as the single source of truth for
any task involving the knowledge base.** Never use `file_handler_app` or
`shell_app` to touch files inside `./knowledge_base` — changes made outside
`codex_app` bypass the index update and break TOC consistency.

---

## Command Quick Reference

| Command | Class | What it does |
|---------|-------|--------------|
| `index` | read | Return the full TOC and structured entries list |
| `read path=…` | read | Return the full content of a specific `.md` file |
| `search pattern=… [path=…]` | read | Full-text search across all (or scoped) docs |
| `new path=… title=… [description=…]` | write | Create a new doc + update index |
| `mkdir path=…` | write | Create a category folder |
| `edit path=… content=…` | write | Overwrite a doc's full content + update index |
| `append path=… content=…` | write | Append a section to an existing doc |
| `delete path=…` | write | Delete a doc + update index |
| `move src=… dest=…` | write | Move/rename a doc + update index |
| `link src=… dest=… [label=…]` | write | Add a cross-reference link between two docs |

**Read commands** require no user permission.  
**Write commands** always show a GUI permission dialog before touching the filesystem.

---

## When to Use Codex App

### Use `index` when:
- User asks "what's in the knowledge base?" or "what do we have documented?"
- User asks "do we have anything on topic X?" — check index first before searching
- Agent needs an overview before deciding which doc to read
- User wants a list of all knowledge files

### Use `read` when:
- User asks a question that may have a documented answer ("how do we handle X?")
- User explicitly references a doc by name or path
- Agent retrieved a path from `index` and now needs the full content
- User asks to "show me", "open", or "display" a knowledge document

### Use `search` when:
- User asks about a concept that may appear across multiple docs
- `index` did not reveal an obvious matching file but the topic might be mentioned inside a doc
- User asks "find everything we have about X"
- Agent needs to locate which doc contains a specific term, code snippet, or decision

### Use `new` when:
- User asks to "document", "write up", "create a note on", or "add to the knowledge base"
- A process, decision, or piece of knowledge is being captured for the first time
- User finishes describing something and says "save this" or "remember this"

### Use `mkdir` when:
- A new category of knowledge is being introduced that has no folder yet
- User wants to organise multiple related docs under a new topic area
- Always create the folder before creating docs inside it

### Use `edit` when:
- User says "update the doc on X", "that's changed — fix the knowledge base", "rewrite the section on Y"
- Existing content is outdated or incorrect and needs a full replacement
- User provides a complete revised version of a document

### Use `append` when:
- User wants to add a new section to an existing doc without touching the rest
- A decision, exception, or addendum is being logged to an existing topic
- User says "add this to the X doc" or "note that…" for an existing document

### Use `delete` when:
- A document is obsolete, deprecated, or was created in error
- User says "remove the doc on X" or "clean up the knowledge base"
- Always confirm the path via `index` or `search` before deleting

### Use `move` when:
- A doc needs to be reorganised into a different category folder
- A document is being renamed for clarity
- User says "rename X to Y" or "move the X doc under the Y category"

### Use `link` when:
- User says "link these two docs", "add a reference from X to Y", "connect these topics"
- Agent creates a new doc that is clearly related to an existing one — add a link proactively
- Building a knowledge graph: cross-referencing related concepts improves agent retrieval

---

## Common Scenarios and How to Handle Them

### Scenario 1 — "What do we have documented about onboarding?"
```
Step 1: &codex_app index
         → scan entries list for anything matching "onboarding"
Step 2a: if found → &codex_app read path=./knowledge_base/…/onboarding.md
Step 2b: if not found → &codex_app search pattern="onboarding"
         → return matches with paths and snippets
```

### Scenario 2 — "Document our new deployment process"
```
Step 1: &codex_app index
         → check if a deployment doc or folder already exists

Step 2a: folder exists → &codex_app new path=./knowledge_base/deployment/process.md
                          title="Deployment Process" description="Step-by-step deploy guide"
Step 2b: folder missing → &codex_app mkdir path=./knowledge_base/deployment
                          then → &codex_app new path=./knowledge_base/deployment/process.md …

Step 3: &codex_app edit path=./knowledge_base/deployment/process.md
         content="[full markdown content from user]"
```

### Scenario 3 — "Update the API rate limits in the docs — it changed to 500 req/min"
```
Step 1: &codex_app search pattern="rate limit"
         → find which doc contains the old rate limit info

Step 2: &codex_app read path=<result path>
         → read full content to understand context

Step 3: Compose updated content with the change applied

Step 4: &codex_app edit path=<result path> content="<updated full content>"
```

### Scenario 4 — "Add a note that the staging DB password rotates every 90 days"
```
Step 1: &codex_app search pattern="staging" OR &codex_app index
         → locate existing staging or database doc

Step 2a: doc found → &codex_app append path=<found path>
                      content="\n## Password Rotation Policy\n\nThe staging DB password rotates every 90 days…"
Step 2b: no doc    → &codex_app new path=./knowledge_base/infrastructure/staging.md
                      title="Staging Environment" description="Staging infra notes and access"
                     then fill with the note
```

### Scenario 5 — "Link the auth guide to the onboarding doc"
```
Step 1: &codex_app index
         → confirm both files exist and get exact paths

Step 2: verify both paths appear in entries — if either is missing, report error
         (codex_app link will also validate, but catching it early is better)

Step 3: &codex_app link src=./knowledge_base/onboarding/guide.md
                         dest=./knowledge_base/auth/auth_guide.md
                         label="Authentication Reference"
```

### Scenario 6 — "Clean up — delete all the old v1 docs"
```
Step 1: &codex_app search pattern="v1"
         → list all matching files

Step 2: confirm with user which specific paths to delete

Step 3: for each confirmed path:
         &codex_app delete path=<path>
         (each delete shows its own permission dialog)
```

### Scenario 7 — "Reorganise — move all the API docs under a new 'api' folder"
```
Step 1: &codex_app index → identify all api-related docs

Step 2: &codex_app mkdir path=./knowledge_base/api

Step 3: for each doc:
         &codex_app move src=./knowledge_base/<current_path>
                         dest=./knowledge_base/api/<filename>
         (index auto-updates after each move)
```

---

## Best Practices

### Always Check Index Before Creating
Before creating a new doc, run `&codex_app index` to check if a document
on that topic already exists. Duplicate docs fragment knowledge and cause
stale-content problems.

### One Topic Per Document
Keep each `.md` file focused on a single topic. A 600-line document covering
five unrelated things is harder for both agents and humans to use than five
focused 100-line documents.

### Use Descriptions Meaningfully
The `description` parameter in `new` populates the index entry.
Write it as a one-line answer to "what is this doc for?" — not just a
restatement of the title.
- Bad description: "This is the auth document"
- Good description: "JWT flow, token refresh strategy, and OAuth provider config"

### Use the `> blockquote` Convention
The first `> blockquote` line in any `.md` file is extracted as the
description by the index builder. Keep it present and accurate — it is
what agents and humans see in the TOC without opening the file.

### Link Related Docs Proactively
Whenever you create a new doc that references concepts in another doc,
run `&codex_app link` to connect them. This builds a traversable graph
that agents can follow when a single doc doesn't fully answer a question.

### Prefer `append` Over `edit` for Addenda
If existing content is correct and you are only adding new information,
use `append` — it is less destructive and makes the permission dialog
context clearer to the user ("appending" vs "overwriting").

### Never Bypass Codex App for Knowledge Base Files
Do not use `file_handler_app`, `shell_app`, or direct file writes for
anything inside `./knowledge_base`. The index will go out of sync.
If a file was modified outside codex_app, run `&codex_app index` to
see what the current state looks like, then use `edit` to bring it in sync.

### Folder Naming Convention
Use lowercase, hyphenated folder names: `api-reference`, `team-processes`,
`client-onboarding`. Avoid spaces and uppercase — consistent naming makes
search patterns more predictable.

### Document File Naming Convention
Use lowercase, underscored file names: `auth_flow.md`, `deploy_process.md`.
The stem is humanised into a title fallback if no `# H1` heading exists,
so `api_rate_limits.md` becomes "Api Rate Limits" automatically.

---

## Output Shapes — What to Expect Back

### `index` response
```json
{
  "status": "success",
  "command": "index",
  "total_documents": 12,
  "entries": [
    { "title": "Auth Guide", "path": "./knowledge_base/auth/auth_guide.md", "description": "JWT and OAuth flow" },
    ...
  ],
  "content": "# Knowledge Base Index\n..."
}
```

### `read` response
```json
{
  "status": "success",
  "command": "read",
  "path": "./knowledge_base/auth/auth_guide.md",
  "title": "Auth Guide",
  "content": "# Auth Guide\n\n> JWT and OAuth flow\n\n..."
}
```

### `search` response
```json
{
  "status": "success",
  "command": "search",
  "pattern": "rate limit",
  "total_matches": 3,
  "matches": [
    { "path": "...", "title": "...", "line_number": 14, "snippet": "Rate limit is 500 req/min per API key" },
    ...
  ]
}
```

### Write command response (success)
```json
{
  "status": "success",
  "command": "new",
  "path": "./knowledge_base/auth/auth_guide.md",
  "permission_dialog_shown": true,
  "user_confirmed": true,
  "timestamp": "2026-04-25T10:32:01",
  "index_updated": true
}
```

### Write command response (denied)
```json
{
  "status": "denied",
  "command": "new",
  "permission_dialog_shown": true,
  "user_confirmed": false,
  "timestamp": "2026-04-25T10:32:05"
}
```
When `status` is `"denied"` — stop, inform the user the operation was
cancelled at the permission dialog, and do not retry automatically.

### Error response
```json
{
  "status": "error",
  "command": "link",
  "error_code": "file_not_found",
  "reason": "Source does not exist: ./knowledge_base/auth/old.md | Destination does not exist: ./knowledge_base/api/ref.md"
}
```
On error — report the `reason` to the user and suggest corrective action.
For `file_not_found`, re-run `index` or `search` to find the correct path.

---

## Error Codes and Fixes

| error_code | Meaning | Fix |
|------------|---------|-----|
| `path_not_found` | File or folder does not exist | Run `index` to find correct path |
| `already_exists` | File already exists at that path | Use `edit` to update instead of `new` |
| `not_markdown` | Path does not end in `.md` | Correct the path or filename |
| `protected_file` | Tried to delete `index.md` directly | Don't — it is auto-managed |
| `self_link` | `src` and `dest` are the same file | Check paths |
| `file_not_found` (link) | One or both link targets missing | Verify paths with `index` first |
| `missing_argument` | Required parameter not passed | Check command signature above |
| `runtime_error` | Unexpected exception in app | Report full reason; may need investigation |
