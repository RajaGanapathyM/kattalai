# Kattalai HTTP API

Once the kattalai runtime is running, it exposes a REST API at:

```
http://127.0.0.1:3077
```

All endpoints use `POST` with `Content-Type: application/json`. A [Streamlit demo app](demo/server_demo.py) is included in the repo.

> **⚠️ Security Note:** The runtime binds to `127.0.0.1` (localhost only) by design. **Do not expose this port to the public internet or a shared network.** There is no authentication layer — anyone who can reach this port has full control over your agents, topics, and messages. If you need remote access, place it behind a secure authenticated proxy.

---

## Contents

- [Core Concepts](#core-concepts)
- [Response Format](#response-format)
- [Correct API Flow](#correct-api-flow)
- [Endpoints](#endpoints)
  - [User](#user)
  - [Topic](#topic)
  - [Agent](#agent)
  - [Messaging](#messaging)
  - [Agent Execution](#agent-execution)
- [Polling Pattern](#polling-pattern)
- [Minimal Working Example](#minimal-working-example)
- [Common Mistakes](#common-mistakes)

---

## Core Concepts

| Concept | Description |
|---|---|
| **User** | The person interacting with the system |
| **Topic** | A conversation thread |
| **Agent** | AI processing unit attached to a topic |
| **Message** | User input sent to a topic |
| **Memory** | Agent output — streamed as episode chunks |

---

## Response Format

All responses follow a consistent envelope:

**Success**
```json
{
  "ok": true,
  "data": "..."
}
```

**Error**
```json
{
  "ok": false,
  "error": "error message"
}
```

Always check `"ok"` before using `"data"`.

---

## Correct API Flow

The runtime is **asynchronous**. Follow this sequence exactly:

```
1.  POST /user/create          → user_id
2.  POST /topic/create         → topic_id
3.  POST /agent/deploy         → agent_id
4.  POST /topic/add-agent      (attach agent to topic)
5.  POST /message/insert       (send a message)
6.  POST /agent/working-status (poll until false)
7.  POST /agent/iter-memory    (fetch agent response)
```

```
User
  ↓  create user
Topic
  ↓  create topic + attach agent
Send Message
  ↓
Agent processing
  ↓  poll /agent/working-status
Fetch /agent/iter-memory
```

---

## Endpoints

### User

#### `POST /user/create`

Register a new user identity.

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
  "data": "<user_id>"
}
```

---

### Topic

#### `POST /topic/create`

Create a new conversation thread.

**Request**
```json
{}
```

**Response**
```json
{
  "ok": true,
  "data": "<topic_id>"
}
```

---

#### `POST /topic/history-len`

Return the total number of messages in a thread. Use this to track a cursor for incremental fetching.

**Request**
```json
{
  "topic_id": "<topic_id>"
}
```

**Response**
```json
{
  "ok": true,
  "data": 4
}
```

---

#### `POST /topic/iter`

Fetch messages from a thread starting at `start_index`.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "start_index": 0
}
```

**Response**
```json
{
  "ok": true,
  "data": [
    { "name": "raja",  "role": "user",      "content": "Hello!" },
    { "name": "DIA",   "role": "assistant",  "content": "```output\nHi! How can I help?\n```" }
  ]
}
```

---

#### `POST /topic/add-agent`

Attach a deployed agent to a topic thread. The agent will respond to new messages in that topic.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "agent_id": "<agent_id>"
}
```

> Attach an agent before sending any messages. Only one agent should be active on a topic at a time.

---

#### `POST /topic/remove-agent`

Detach an agent from a topic thread.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "agent_id": "<agent_id>"
}
```

---

### Agent

#### `POST /agents/list`

Return all agent names defined in `agents_config.toml`.

**Request**
```json
{}
```

**Response**
```json
{
  "ok": true,
  "data": ["DIA", "Researcher", "Coder"]
}
```

---

#### `POST /agent/deploy`

Deploy a named agent and return its ID.

**Request**
```json
{
  "agent_name": "DIA"
}
```

**Response**
```json
{
  "ok": true,
  "data": "<agent_id>"
}
```

---

### Messaging

#### `POST /message/insert`

Insert a user message into a topic thread. Triggers the attached agent to begin processing.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "user_id":  "<user_id>",
  "message":  "Hello agent"
}
```

---

### Agent Execution

#### `POST /agent/working-status`

Check whether an agent is currently processing a message.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "agent_id": "<agent_id>"
}
```

**Response**
```json
{
  "ok":   true,
  "data": true
}
```

| `data` value | Meaning |
|---|---|
| `true` | Agent is still processing |
| `false` | Agent has finished — safe to fetch memory |

---

#### `POST /agent/iter-memory`

Fetch agent episode entries (internal working memory) from `start_index` onward.

**Request**
```json
{
  "topic_id":    "<topic_id>",
  "agent_id":    "<agent_id>",
  "start_index": 0
}
```

**Response**
```json
{
  "ok": true,
  "data": [
    {
      "name":    "DIA",
      "role":    "assistant",
      "content": "```thoughts\nUser is greeting...\n```\n```output\nHello! How can I help?\n```"
    }
  ]
}
```

---

#### `POST /agent/episode-history-len`

Return the number of entries in the agent's episode memory for a given topic.

**Request**
```json
{
  "topic_id": "<topic_id>",
  "agent_id": "<agent_id>"
}
```

---

## Polling Pattern

The runtime processes messages asynchronously. After sending a message you **must** poll before fetching the response:

```python
import time, requests

BASE = "http://127.0.0.1:3077"

def api(path, body=None):
    r = requests.post(BASE + path, json=body or {})
    j = r.json()
    if j["ok"]:
        return j["data"]
    raise Exception(j["error"])

# Send message
api("/message/insert", {
    "topic_id": topic_id,
    "user_id":  user_id,
    "message":  "Hello!"
})

# Poll until done
while api("/agent/working-status", {"topic_id": topic_id, "agent_id": agent_id}):
    time.sleep(1.5)

# Fetch response
memory = api("/agent/iter-memory", {
    "topic_id":    topic_id,
    "agent_id":    agent_id,
    "start_index": 0
})
```

**Extracting content from memory nodes:**

```python
for node in memory:
    text = (
        node.get("content") or
        node.get("message") or
        node.get("text") or
        str(node)
    )
    print(text)
```

---

## Minimal Working Example

Complete end-to-end flow in Python:

```python
import requests
import time

BASE = "http://127.0.0.1:3077"


def api(path, body=None):
    r = requests.post(BASE + path, json=body or {})
    j = r.json()
    if j["ok"]:
        return j["data"]
    raise Exception(j["error"])


# 1. Setup
user_id  = api("/user/create",  {"user_name": "raja"})
topic_id = api("/topic/create")
agent_id = api("/agent/deploy", {"agent_name": "DIA"})

api("/topic/add-agent", {"topic_id": topic_id, "agent_id": agent_id})

# 2. Send a message
api("/message/insert", {
    "topic_id": topic_id,
    "user_id":  user_id,
    "message":  "Hello!"
})

# 3. Poll until the agent finishes
while api("/agent/working-status", {"topic_id": topic_id, "agent_id": agent_id}):
    time.sleep(1.5)

# 4. Fetch and print the response
memory = api("/agent/iter-memory", {
    "topic_id":    topic_id,
    "agent_id":    agent_id,
    "start_index": 0
})

for node in memory:
    print(node.get("content") or node.get("message") or str(node))
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Sending a message before attaching an agent | Always call `/topic/add-agent` first |
| Expecting an immediate response | Always poll `/agent/working-status` after every `/message/insert` |
| Passing `start_index: 0` every time | Track a cursor to avoid receiving duplicate messages |
| Not checking `"ok"` in the response | Check `ok` before accessing `data` |
