# ⬡ Kattalai Runtime API
Once kattalai app is launched the runtime launches along with an HTTP Server in the below url

An streamlit demo app is attached to /demo/server_demo.py

```bash
http://127.0.0.1:3077
```

⚠️ Important: kattalai app by default spins up a server at 127.0.0.1. if you don't want server set bind=None while launching the runtime.

Binding to public ports:
Do not expose this service to the public internet without proper security controls (such as authentication, HTTPS, and firewall rules). Failure to secure it may result in unauthorized access, data breaches, or system compromise.

For safe usage, bind the service to localhost (127.0.0.1) during development.

⚠️ Advisory: While binding to localhost restricts access to your machine, it is not completely risk-free. Make sure there is no malicious local applications. Always run in a trusted environment and avoid unintentionally exposing local ports to public (e.g., via tunneling or port forwarding tools).

# Core Concepts

| Concept     | Description                            |
| ----------- | -------------------------------------- |
| **User**    | The person interacting with the system |
| **Topic**   | A conversation thread                  |
| **Agent**   | Processing unit (AI / logic engine)    |
| **Message** | User input                             |
| **Memory**  | Agent output (streamed chunks)         |

---

# Base URL

```bash
http://127.0.0.1:3077
```

All APIs use:

```bash
POST
Content-Type: application/json
```

---

# Response Format

### Success

```json
{
  "ok": true,
  "data": ...
}
```

### Error

```json
{
  "ok": false,
  "error": "error message"
}
```

---

# Correct API Flow (IMPORTANT)

```text
1. Create User
2. Create Topic
3. Deploy Agent
4. Attach Agent to Topic
5. Send Message
6. Poll Agent Status
7. Fetch Agent Memory (Response)
```

---

# 🔄 Flow Diagram

```text
User
  ↓
Topic (thread)
  ↓
Attach Agent
  ↓
Send Message
  ↓
Agent processing
  ↓
Poll (/agent/working-status)
  ↓
Fetch (/agent/iter-memory)
```

---

# API Reference

---

## 👤 User

### Create User

```http
POST /user/create
```

**Request**

```json
{
  "user_name": "raja"
}
```

**Response**

```json
{
  "ok": true,
  "data": "user_id"
}
```

---

## 🧵 Topic

### Create Topic

```http
POST /topic/create
```

**Request**

```json
{}
```

---

### Topic History Length

```http
POST /topic/history-len
```

```json
{
  "topic_id": "topic_id"
}
```

---

### Iterate Topic

```http
POST /topic/iter
```

```json
{
  "topic_id": "topic_id",
  "start_index": 0
}
```

---

## Agent

### List Agents

```http
POST /agents/list
```

---

### Deploy Agent

```http
POST /agent/deploy
```

```json
{
  "agent_name": "agent_name"
}
```

---

### Attach Agent

```http
POST /topic/add-agent
```

```json
{
  "topic_id": "topic_id",
  "agent_id": "agent_id"
}
```

---

### Detach Agent

```http
POST /topic/remove-agent
```

---

## Messaging

### Send Message

```http
POST /message/insert
```

```json
{
  "topic_id": "topic_id",
  "user_id": "user_id",
  "message": "Hello agent"
}
```

---

## Agent Execution

### Check Working Status

```http
POST /agent/working-status
```

```json
{
  "topic_id": "topic_id",
  "agent_id": "agent_id"
}
```

**Response**

```json
{
  "ok": true,
  "data": true
}
```

* `true` → still working
* `false` → finished

---

### Fetch Agent Memory (Response)

```http
POST /agent/iter-memory
```

```json
{
  "topic_id": "topic_id",
  "agent_id": "agent_id",
  "start_index": 0
}
```

---

### Episode History Length

```http
POST /agent/episode-history-len
```

---

# Polling Pattern (CRITICAL)

Kattalai is **asynchronous**.

After sending a message:

```python
import time

while True:
    working = api("/agent/working-status", {...})
    
    if not working:
        break
    
    time.sleep(1.5)

# Then fetch response
memory = api("/agent/iter-memory", {...})
```

---

# Memory Handling

Agent responses come as **nodes**:

```python
text = (
    node.get("content") or
    node.get("message") or
    node.get("text") or
    str(node)
)
```

---

# Minimal Working Example

```python
import requests
import time

BASE = "http://127.0.0.1:3077"

def api(path, body=None):
    r = requests.post(BASE + path, json=body)
    j = r.json()
    if j["ok"]:
        return j["data"]
    else:
        raise Exception(j["error"])

# Setup
user_id = api("/user/create", {"user_name": "raja"})
topic_id = api("/topic/create")
agent_id = api("/agent/deploy", {"agent_name": "agent1"})

api("/topic/add-agent", {
    "topic_id": topic_id,
    "agent_id": agent_id
})

# Send message
api("/message/insert", {
    "topic_id": topic_id,
    "user_id": user_id,
    "message": "Hello!"
})

# Poll
while api("/agent/working-status", {
    "topic_id": topic_id,
    "agent_id": agent_id
}):
    time.sleep(1.5)

# Fetch response
response = api("/agent/iter-memory", {
    "topic_id": topic_id,
    "agent_id": agent_id,
    "start_index": 0
})

print(response)
```

---

# Mistakes to avoid

* Not attaching agent before sending message
* Expecting immediate response (no polling)
* Ignoring `start_index` (duplicates)
* Not checking `"ok"` in response

---

