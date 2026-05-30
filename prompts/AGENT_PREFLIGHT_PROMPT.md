# PREFLIGHT ANALYSIS PROMPT

Run a preflight analysis on the user query. Output ONLY the fenced block below — no preamble, no commentary, nothing outside it.
Also dont cover about app or protocol or any subworker existance.focus only on knowledge,data,facts,information needed.

```preflight
### ① KNOWLEDGE INVENTORY
- **Confirmed:** facts certain from context or prior outputs
- **Uncertain:** recalled but unverified
- **Assumed:** treated as true without confirmation
- **User-provided:** data, code, config, or constraints in this conversation

### ② GAP DETECTION
World knowledge and domain facts only. For each gap: what · why it matters · blocker or quality risk.
Scope: missing facts, ambiguous concepts, stale technical knowledge.
Skip: app schemas, runtime state, file paths, environment vars.

### ③ RETRIEVAL PLAN
One line per gap. Do NOT execute.
Priority: &codex_app → &wikipedia_app → infer → ask user
Format: `[gap] → [command or "infer from context"] → [expected outcome]`

### ④ PITFALL RADAR
- **Wrong assumption:** belief that, if false, breaks the approach
- **Scope creep:** where task could silently expand
- **Common mistake:** errors typical for this domain
- **Resolution trap:** solution that seems right but causes downstream problems

### ⑤ IDEAL TARGET STATE
Final output description + constraints + what user gains.

### ⑥ CONTEXT CAPSULE
3–5 lines: core task · critical knowns · key gaps (retrieval planned?) · primary pitfall · target state.
```

---

## Rules

- Output MUST be wrapped in ```preflight ``` — nothing outside
- Tags inline: `[confirmed]` `[assumed]` `[uncertain]` `[missing]`
- Empty section → `— none`
- Section ③: commands only, no results
- Total: 150–300 words inside the block

---

## Example

**Query:** *"Add JWT auth to the Axum API layer in soulengine."*

```preflight
### ① KNOWLEDGE INVENTORY
- Kattalai uses Axum as HTTP layer [confirmed]
- soulengine is the Rust core [confirmed]
- JWT is a stateless token standard [confirmed]
- Current Axum middleware setup [uncertain]
- JWT crate in use (jsonwebtoken / jwt-simple) [missing]
- Existing codex auth entry [missing]

### ② GAP DETECTION
- [missing] JWT crate — blocks implementation; different crates have incompatible APIs
- [missing] Codex auth entry — risk of duplicating prior decisions
- [uncertain] Token expiry/refresh strategy — quality risk, not a blocker

### ③ RETRIEVAL PLAN
[auth pattern] → &codex_app search pattern="authentication" → prior JWT decision, preferred crate
[JWT structure] → &wikipedia_app summary title="JSON Web Token" → header/payload/signature reference

### ④ PITFALL RADAR
- Wrong assumption: no auth protocol in codex → duplication risk
- Scope creep: expanding into refresh tokens when only access token asked
- Common mistake: hardcoding JWT secret in source
- Resolution trap: per-route auth instead of shared Axum middleware layer

### ⑤ IDEAL TARGET STATE
Axum middleware validating Bearer JWT on protected routes. Routes opt in via layer. Secret from env. Crate choice recorded in codex.

### ⑥ CONTEXT CAPSULE
Task: JWT auth middleware for Axum in soulengine.
Known: Axum = HTTP layer; JWT structure clear.
Gaps: crate [missing]; codex entry [missing] — retrieval planned.
Pitfall: per-route impl instead of shared layer.
Target: reusable Axum layer validating Bearer tokens.
```