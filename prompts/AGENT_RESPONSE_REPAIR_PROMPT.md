# FORMAT REPAIR REQUIRED

Your previous response did not follow the required format. The validator found these errors:

{validator_errors}

---

Rewrite your previous response correctly. Same content, fixed structure.

## Rules to follow:
- `thoughts` block — always first, always present
- `terminal` block — only if issuing app commands
- `output` block — only when messaging the user
- `followup_context` block — mandatory if needs_followup=True
- `validation` block — always last, flags must match blocks present

## Hard constraints:
- `followup_context=False` + `needs_followup=True` → forbidden
- Validation flags must exactly match which blocks you included
- One validation block only, always last
- Every block must be wrapped in triple backticks with its name — bare text is invalid

---

## Complete Block Structure Reference
```thoughts
[Your reasoning and plan here. Always required.]
```
```terminal
[App commands here. One per line. Omit this block if no commands.]
```
```output
[User-facing message here. Omit while waiting for app results.]
```
```followup_context
[Step position, pending command, next action, remaining steps, decision rules, state, done condition.]
```
```validation
thoughts=True|False
terminal=True|False
output=True|False
followup_context=True|False
needs_followup=True|False
```

---

Previous malformed response:
{malformed_response}

---

Now output the corrected response below. Do not explain or apologize. Do not write block names as plain text — every block must use the exact ```blockname``` fence syntax shown above.