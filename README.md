# SafeMailSkill

A skill for OpenClaw agents that allows **safe, human-in-the-loop** access to a [Fastmail](https://fastmail.com) account via [JMAP](https://jmap.io/).

## Overview

SafeMailSkill prevents an AI agent from sending email or permanently deleting messages without explicit human approval. It exposes three endpoints that the agent can call:

| Endpoint | Method | Action |
|---|---|---|
| `/v1/delete` | `POST` | Shadow-delete: moves the email to `ai_trash` (never permanently deleted). |
| `/v1/send` | `POST` | Stages a draft in `ai_outgoing` and sends a PIN notification to you. |
| `/v1/approve` | `POST` | Verifies the PIN and sends the staged draft (expires after 1 hour). |

## Architecture

### Folder-based State (Zero Local Database)

The skill uses two Fastmail folders to track the AI's actions:

- **`ai_trash`** – a graveyard for emails the AI "deleted". They are always recoverable.
- **`ai_outgoing`** – a staging area for drafts awaiting your PIN approval.

Pending PINs and creation timestamps are embedded directly into JMAP email **keywords** (e.g., `$ai_pin_1234`, `$ai_ts_1700000000`), so the service is fully stateless — a crash or restart loses nothing.

### Logic Flow

#### Shadow Delete
1. Agent calls `POST /v1/delete` with an `email_id`.
2. Service uses JMAP `Email/set` to remove the email from its current mailbox and add it to `ai_trash`.
3. Returns `{"status": "success"}` to the agent.

#### HITL Send
1. Agent calls `POST /v1/send` with `to`, `subject`, and `body`.
2. Service generates a 4-digit PIN.
3. Service creates a JMAP draft in `ai_outgoing` with the PIN stored as a keyword.
4. Service sends a push notification (ntfy or Telegram) with the email summary and PIN.
5. Returns `{"status": "pending"}` to the agent — **email is NOT sent yet**.

#### Verification & Execution
1. You receive the notification and open Fastmail to review the draft in `ai_outgoing`.
2. If you approve, call `POST /v1/approve` with the PIN.
3. Service searches `ai_outgoing` for a draft with that PIN keyword.
4. If found and not expired (< 1 hour), it submits the email via `EmailSubmission/set` and deletes the draft.

## Setup

### 1. Prerequisites

- Python 3.11+
- A [Fastmail](https://fastmail.com) account with an App Password (restricted to "Mail" access).

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
FASTMAIL_TOKEN=your-fastmail-app-password

# Notification backend: "ntfy" or "telegram"
NOTIFIER=ntfy
NTFY_TOPIC=my-safemail-topic
```

### 4. Run the Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API docs are available at `http://localhost:8000/docs`.

### 5. Register with OpenClaw

Point OpenClaw at `skill.json` (or the live server URL). The skill definition is in [`skill.json`](./skill.json).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FASTMAIL_TOKEN` | *(required)* | Fastmail App Password with Mail access. |
| `AI_TRASH_FOLDER` | `ai_trash` | Folder name for shadow-deleted emails. |
| `AI_OUTGOING_FOLDER` | `ai_outgoing` | Folder name for pending drafts. |
| `PIN_EXPIRY_SECONDS` | `3600` | How long a PIN is valid (seconds). |
| `NOTIFIER` | `ntfy` | Notification backend: `ntfy` or `telegram`. |
| `NTFY_TOPIC` | *(empty)* | ntfy topic name (required if `NOTIFIER=ntfy`). |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server URL. |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram bot token (required if `NOTIFIER=telegram`). |
| `TELEGRAM_CHAT_ID` | *(empty)* | Telegram chat ID (required if `NOTIFIER=telegram`). |

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Security Notes

- The Fastmail App Password should be scoped to **Mail only**.
- PINs expire after 1 hour to limit the attack window.
- Expired drafts are automatically deleted from `ai_outgoing` when an expired PIN is submitted.
- The service does **not** expose any authentication endpoint itself — deploy behind a reverse proxy with TLS if exposed publicly.
