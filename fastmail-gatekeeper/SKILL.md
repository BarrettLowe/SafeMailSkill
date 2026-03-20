---
name: fastmail-gatekeeper
description: Read, search, triage, and safely manage Fastmail email via JMAP. Use when working with email: reading the inbox, searching messages, fetching thread context, safely trashing email (never permanent delete), or drafting and sending email requiring human PIN approval. Handles trash_email, send_email, approve_email, and all general read operations.
compatibility: Requires the gatekeeper server to be running and reachable. See references/SETUP.md for operator setup instructions.
metadata: {"openclaw": {"requires": {"env": ["GATEKEEPER_API_KEY"], "bins": ["curl"]}}}
---

# Fastmail Gatekeeper

A secure mail API that gives the agent safe, auditable access to email.
All requests require authentication and all permanent deletion is blocked
at the server level.

**Base URL:** `http://127.0.0.1:8080`

Every `/v1/*` request requires:
```
Authorization: Bearer $GATEKEEPER_API_KEY
```

---

## Safety Rules — read before acting

- **Never use `Email/destroy`.** It is blocked by the server and will return 403.
- **Never call `EmailSubmission/set` via `/v1/jmap`.** It is blocked.
- **Always use `trash_email` (`POST /v1/delete`) to discard email.** This moves the message to `ai_trash`; it is not permanent and can be recovered.
- **Email sending always requires human approval.** Use `/v1/send` (creates draft + sends PIN) then wait for the user to call `/v1/approve` with the PIN.

---

## trash_email — safe "delete"

Moves a message to `ai_trash`. **Not permanent. Always prefer this over any other deletion method.**

```bash
curl -s -X POST http://127.0.0.1:8080/v1/delete \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message_id": "<EMAIL_ID>"}'
```

**Success:**
```json
{"status": "success", "message": "Email moved to ai_trash"}
```

---

## send_email — draft + approval flow

Creates a draft in `ai_outgoing` and sends a PIN push notification via ntfy. The email is **not sent** until `approve_email` is called.

```bash
curl -s -X POST http://127.0.0.1:8080/v1/send \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "recipient@example.com",
    "subject": "Subject here",
    "body": "Plain text body."
  }'
```

**Response (pending — not yet sent):**
```json
{"status": "pending", "message": "Approval required. Check your mobile device."}
```

---

## approve_email — confirm and send

After the user receives the PIN on their device, submit the queued draft:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/approve \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pin": "1234"}'
```

**Responses:**
```json
{"status": "sent"}
```
```json
{"status": "error", "message": "Invalid PIN"}
```

---

## Reading mail via the JMAP proxy

For all read/search/label/move operations use `POST /v1/jmap`.

You do not need to supply `accountId` — the server injects it automatically.
Just provide the `methodCalls` array.

Request shape:
```json
{
  "methodCalls": [
    ["MethodName", { ...args... }, "callId"],
    ...
  ]
}
```

Response shape (passed through from Fastmail):
```json
{
  "methodResponses": [
    ["MethodName", { ...result... }, "callId"],
    ...
  ],
  "sessionState": "..."
}
```

### List mailboxes

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Mailbox/get", {"ids": null}, "c1"]
    ]
  }'
```

Each mailbox entry includes: `id`, `name`, `role`, `totalEmails`, `unreadEmails`, `parentId`.

Common `role` values: `inbox`, `sent`, `drafts`, `trash`, `spam`, `archive`.

### Search / list emails

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Email/query", {
        "filter": {
          "inMailbox": "<MAILBOX_ID>",
          "text": "optional search term"
        },
        "sort": [{"property": "receivedAt", "isAscending": false}],
        "limit": 20,
        "position": 0
      }, "c1"],
      ["Email/get", {
        "#ids": {"resultOf": "c1", "name": "Email/query", "path": "/ids"},
        "properties": ["id", "threadId", "subject", "from", "to", "receivedAt", "preview", "keywords"]
      }, "c2"]
    ]
  }'
```

**Supported `filter` fields:**

| Field | Type | Description |
|---|---|---|
| `inMailbox` | string | Mailbox ID to restrict search |
| `text` | string | Full-text search across all fields |
| `from` | string | Sender address (partial match) |
| `to` | string | Recipient address (partial match) |
| `subject` | string | Subject line (partial match) |
| `hasKeyword` | string | JMAP keyword e.g. `"$seen"`, `"$flagged"` |
| `notKeyword` | string | Exclude messages with this keyword |
| `after` | UTCDate | e.g. `"2026-01-01T00:00:00Z"` |
| `before` | UTCDate | e.g. `"2026-03-01T00:00:00Z"` |
| `minSize` / `maxSize` | int | Message size in bytes |

### Fetch a full email with body

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Email/get", {
        "ids": ["<MESSAGE_ID>"],
        "properties": [
          "id", "threadId", "subject", "from", "to", "cc", "replyTo",
          "receivedAt", "keywords", "textBody", "bodyValues"
        ],
        "fetchTextBodyValues": true,
        "maxBodyValueBytes": 32768
      }, "c1"]
    ]
  }'
```

The plain-text body is in `bodyValues[<partId>].value`, where `<partId>` comes
from `textBody[0].partId` in the response.

### Fetch a thread

First, get the `threadId` from an `Email/get` or `Email/query` result
(add `"threadId"` to `properties`). Then:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Thread/get", {
        "ids": ["<THREAD_ID>"]
      }, "c1"],
      ["Email/get", {
        "#ids": {
          "resultOf": "c1",
          "name": "Thread/get",
          "path": "/list/*/emailIds"
        },
        "properties": ["id", "subject", "from", "receivedAt", "preview", "keywords"]
      }, "c2"]
    ]
  }'
```

### Move email to a different mailbox

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Email/set", {
        "update": {
          "<MESSAGE_ID>": {
            "mailboxIds": {"<DESTINATION_MAILBOX_ID>": true}
          }
        }
      }, "c1"]
    ]
  }'
```

Note: setting `mailboxIds` to `{}` or `null` is blocked (equivalent to deletion).

### Mark as read / flag

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jmap \
  -H "Authorization: Bearer $GATEKEEPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "methodCalls": [
      ["Email/set", {
        "update": {
          "<MESSAGE_ID>": {
            "keywords/$seen": true
          }
        }
      }, "c1"]
    ]
  }'
```

Use `"keywords/$flagged": true` to star a message.
Use `null` instead of `true` to remove a keyword.

---

## Error Responses

| HTTP | Meaning |
|------|---------|
| 401 | Missing or invalid `Authorization: Bearer` header |
| 403 | Blocked JMAP method — response body includes `blockedCalls` list |
| 404 | PIN not found / message not found |
| 422 | Validation error (bad email address, PIN not 4 digits, etc.) |
| 502 | Server-side or upstream error — the request reached the server but could not be completed |

**Blocked method response:**
```json
{
  "status": "blocked",
  "reason": "One or more method calls are not permitted by gatekeeper policy",
  "blockedCalls": [
    {"method": "Email/destroy", "callId": "c1", "reason": "Method not permitted by gatekeeper policy"}
  ]
}
```


See [references/JMAP_REFERENCE.md](references/JMAP_REFERENCE.md) for a fuller JMAP property and filter reference.
