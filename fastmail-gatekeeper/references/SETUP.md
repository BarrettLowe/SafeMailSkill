# Gatekeeper — Operator Setup Guide

This file is for the human operator. The agent does not need to read this.

## Prerequisites

- Docker + Docker Compose
- A Fastmail account with an App Password (Mail access only)
- The `ntfy` app installed on your phone, subscribed to your topic

## 1. Configure environment

```bash
cp .env.example .env
```

Fill in all values in `.env`:

| Variable | Description |
|---|---|
| `FASTMAIL_TOKEN` | Fastmail App Password with Mail access |
| `AI_TRASH_ID` | Mailbox ID for the "ai_trash" folder |
| `AI_OUTGOING_ID` | Mailbox ID for the "ai_outgoing" folder |
| `NTFY_TOPIC` | Your unique ntfy.sh topic string |
| `GATEKEEPER_API_KEY` | Secret bearer token for the agent |

Run `python scripts/list_mailboxes.py` (with `FASTMAIL_TOKEN` set) to print
all mailbox IDs so you can find the correct values for `AI_TRASH_ID` and
`AI_OUTGOING_ID`. Create those folders in Fastmail first if they don't exist.

Generate a strong API key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Start the server

```bash
docker compose up --build -d
```

Verify it's running:
```bash
curl -s http://127.0.0.1:8080/health
# Expected: {"status":"ok"}
```

## 3. Configure OpenClaw

Place this skill folder under `~/.openclaw/workspace/skills/fastmail-gatekeeper`
(or your agent's workspace skills directory) and restart/refresh the gateway.

Set `GATEKEEPER_API_KEY` in the agent's environment so OpenClaw can inject it
into the skill via `skills.entries.fastmail-gatekeeper.env`.

## Verification checklist

- `POST /v1/delete` uses `Email/set` to move mail — it does **not** call `Email/destroy`.
- The PIN is stored in the draft as a JMAP keyword (`ai-pin-NNNN`), never in a database.
- Every `/v1/*` endpoint returns 401 when the `Authorization` header is missing or wrong.
