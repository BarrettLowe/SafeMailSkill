---
name: fastmail-gatekeeper
description: Read, search, triage, and safely manage Fastmail email via JMAP. Use when working with email: reading the inbox, searching messages, fetching thread context, safely trashing email (never permanent delete), or drafting and sending email requiring human PIN approval.
compatibility: Requires the gatekeeper server to be running and reachable. See references/SETUP.md for operator setup instructions.
metadata: {"openclaw": {"requires": {"env": ["GATEKEEPER_API_KEY"], "bins": ["python3"]}}}
---

# Fastmail Gatekeeper

Use `scripts/gatekeeper.py` for all operations. It reads `GATEKEEPER_API_KEY` from
the environment and always prints JSON to stdout. Errors go to stderr with an
`"error"` key (or `"http_status"` for HTTP errors).

---

## Safety rules

- Never use `Email/destroy` or `EmailSubmission/set` — both are blocked (403).
- To discard email use `trash` — it moves the message to `ai_trash`, not permanent.
- Sending always requires human approval: call `send`, then wait for the user to
  call `approve` with the PIN shown on their device.

---

## Commands

```
python scripts/gatekeeper.py list-mailboxes
```
Returns `[{id, name, role, totalEmails, unreadEmails}]` sorted by role then name.

```
python scripts/gatekeeper.py list-emails <mailbox_id> [options]
  --limit N        default 20
  --search TEXT    full-text across all fields
  --from ADDR      sender partial match
  --subject TEXT   subject partial match
  --unread         only unseen messages
  --after  ISO     e.g. 2026-01-01T00:00:00Z
  --before ISO
```

```
python scripts/gatekeeper.py get-email  <message_id>
python scripts/gatekeeper.py get-thread <thread_id>
```
`get-email` returns the full message including `textBody`/`bodyValues`.
The plain-text body is at `bodyValues[textBody[0].partId].value`.

```
python scripts/gatekeeper.py trash   <message_id>     # moves to ai_trash
python scripts/gatekeeper.py move    <message_id> <mailbox_id>
python scripts/gatekeeper.py mark-read   <message_id>
python scripts/gatekeeper.py mark-unread <message_id>
python scripts/gatekeeper.py flag        <message_id>
python scripts/gatekeeper.py unflag      <message_id>
```

```
python scripts/gatekeeper.py send    <to> <subject> <body>
# → {"status": "pending", "message": "Approval required. Check your mobile device."}

python scripts/gatekeeper.py approve <pin>
# → {"status": "sent"}  or  {"status": "error", "message": "Invalid PIN"}
```

---

## HTTP error codes (returned in JSON via stderr)

| Code | Meaning |
|------|---------|
| 401  | Missing or invalid API key |
| 403  | Blocked JMAP method |
| 404  | PIN or message not found |
| 422  | Validation error |
| 502  | Upstream error |

See [references/JMAP_REFERENCE.md](references/JMAP_REFERENCE.md) for full JMAP property/filter reference.
