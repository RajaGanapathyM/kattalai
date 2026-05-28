## PREFLIGHT ANALYSIS

### ① KNOWLEDGE INVENTORY
Scan the current conversation and your internal knowledge.
List what you know that is directly relevant to the user query:
- **Known (confirmed):** facts, context, or prior outputs you are certain of
- **Known (uncertain):** things you recall but cannot fully verify
- **Assumed:** things you are treating as true without explicit confirmation
- **Provided by user:** any data, code, config, or constraints given in this conversation

---

### ② GAP DETECTION
Identify what is missing or unclear — **world knowledge and domain facts only**.

**In scope:**
- Missing facts or definitions about the subject matter
- Ambiguous terms or domain concepts
- Stale / version-sensitive technical knowledge
- Domain knowledge you lack or are uncertain about

**Out of scope — do not flag:**
- App input formats, parameter schemas, or required fields
- How to call or configure an app
- Whether a capable app already exists in the runtime 
- Runtime state, file paths, or environment variables

For each gap, state: what is missing · why it matters · whether it blocks progress or is a quality risk.

---

### ③ RETRIEVAL PLAN
For each significant gap, write the exact app command to run.
**Do NOT execute — output as a ready-to-use command block.**

Priority order:
1. `&codex_app`      — existing protocols, decisions, patterns
3. `&wikipedia_app`  — domain concepts, background theory, terminology
4. Direct inference  — if retrieval would be overkill for a small gap
5. Ask the user      — only if gap is critical and cannot be resolved otherwise

For each gap, one line:
```
[gap label] → [command] → [what you expect to learn]
```

If no retrieval needed:
```
[gap label] → infer from context → [reasoning in one line]
```

---

### ④ PITFALL RADAR
Think ahead. List the most likely ways this task could go wrong:
- **Wrong assumption:** a prior belief that, if false, would break the approach
- **Scope creep risk:** where this could silently expand beyond what was asked
- **Common mistake:** errors typical for this domain or task type
- **Resolution trap:** a solution that seems right but creates downstream problems

Be specific — vague warnings like "make sure to test" are not useful here.

---

### ⑤ IDEAL TARGET STATE
Describe what a successful resolution looks like:
- What the final output or state should be
- What constraints or quality criteria must be met
- What the user will be able to do / know / have after completion

This is the success definition. All subsequent steps must aim toward it.

---

### ⑥ CONTEXT CAPSULE
A tight 3–6 line summary capturing:
- The core task
- The critical known facts
- The most important gaps (and whether retrieval is planned)
- The primary pitfall to avoid
- The target state in one line

This capsule will be prepended to each subsequent reasoning step as working memory.

---

**Format rules:**
- Use headers exactly as labelled (①–⑥)
- Keep each section factual and terse — no speculation padding
- Tag confidence inline: `[confirmed]` `[assumed]` `[uncertain]` `[missing]`
- If a section has nothing to report, write `— none identified`
- Section ③ outputs commands only — do not execute, do not fabricate results
- Aim for 200–350 words total

---

## Example [PREFLIGHT]

*Task: "Add JWT authentication to the Axum API layer in soulengine."*

```
[PREFLIGHT]

### ① KNOWLEDGE INVENTORY
- Kattalai uses Axum as the HTTP API layer [confirmed]
- soulengine is the Rust core [confirmed]
- JWT is a stateless token standard [confirmed]
- Current middleware setup in Axum routes [unknown]
- Which crate is used for JWT (jsonwebtoken, jwt-simple, etc.) [missing]
- Whether an auth protocol already exists in the codex [missing]

### ② GAP DETECTION
- [missing] JWT crate choice — blocks implementation; different crates have different APIs
- [missing] Existing codex entry for auth — could duplicate prior work
- [uncertain] Token expiry and refresh strategy — quality risk, not a blocker

### ③ RETRIEVAL PLAN
[auth pattern unknown]
→ &codex_app search pattern="authentication" path=./knowledge_base/auth
→ expect: prior JWT decision, preferred crate, expiry strategy

[JWT structure unfamiliar]
→ &wikipedia_app summary title="JSON Web Token"
→ expect: header/payload/signature structure, standard claims reference

### ④ PITFALL RADAR
- Wrong assumption: assuming no auth protocol exists in codex — could cause duplication
- Scope creep: expanding into refresh token flows when only access token was asked for
- Common mistake: storing JWT secret in source code rather than environment config
- Resolution trap: implementing auth at route level instead of as a shared Axum layer

### ⑤ IDEAL TARGET STATE
Axum middleware that validates a Bearer JWT on protected routes.
Pluggable: routes opt in via a layer, not hardcoded per handler.
Secret loaded from environment. Crate choice recorded in codex after.

### ⑥ CONTEXT CAPSULE
Task: add JWT auth middleware to the Axum layer in soulengine.
Known: Axum is the HTTP layer; JWT structure understood.
Gaps: crate choice [missing]; existing codex entry [missing];
Pitfall: do not implement per-route; must be a shared middleware layer.
Target: a reusable Axum layer that validates Bearer tokens on protected routes.
```