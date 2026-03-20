Project Specification: Fastmail Gatekeeper Skill
1. Goal

Build a Python-based FastAPI server that proxies Fastmail JMAP requests. It must prevent actual deletions by redirecting them to a "shadow" folder and gatekeep outgoing emails via a PIN-based Human-in-the-Loop (HITL) flow.
2. Core Components

    API Framework: FastAPI.

    Mail Protocol: JMAP (using requests for JSON-RPC).

    Notification: ntfy.sh (or a similar lightweight push service).

    Deployment: Docker + Docker Compose.

3. Developer Instructions for the Agent
Phase 1: Environment & Setup

Create a .env file template and a config.py to handle:

    FASTMAIL_TOKEN: An App Password with "Mail" access.

    NTFY_TOPIC: A unique string for your push notifications.

    AI_TRASH_ID: The JMAP ID for the ai_trash folder.

    AI_OUTGOING_ID: The JMAP ID for the ai_outgoing folder.

    GATEKEEPER_API_KEY: A secret key so only your AI can call this skill.

Phase 2: The JMAP Client

Implement a JMAPClient class with the following methods:

    get_session(): Connect to https://api.fastmail.com/jmap/session.

    move_to_folder(message_id, folder_id): Uses Email/set to update mailboxIds.

    create_draft(recipient, subject, body, pin):

        Creates an email in ai_outgoing.

        Crucial: Store the pin in the keywords property of the JMAP object (e.g., keywords: {"ai-pin-1234": true}).

    find_draft_by_pin(pin): Queries ai_outgoing for messages containing the keyword ai-pin-{pin}.

    submit_email(message_id): Uses EmailSubmission/set to send the finalized draft.

Phase 3: API Endpoint Logic

1. POST /v1/delete

    Input: message_id.

    Action: Call move_to_folder(message_id, AI_TRASH_ID).

    Response: {"status": "success", "message": "Email moved to ai_trash"}.

2. POST /v1/send

    Input: to, subject, body.

    Action: 1. Generate a random 4-digit PIN.
    2. Call create_draft(...) with the PIN as a keyword.
    3. Send a POST request to https://ntfy.sh/{NTFY_TOPIC} with the text: "AI wants to send email to {to}. PIN: {pin}".

    Response: {"status": "pending", "message": "Approval required. Check your mobile device."}.

3. POST /v1/approve

    Input: pin.

    Action: 1. Search ai_outgoing for the draft with that PIN keyword.
    2. If found, call submit_email(message_id).

    Response: {"status": "sent"} or {"status": "error", "message": "Invalid PIN"}.

4. Dockerization

Create a Dockerfile using python:3.11-slim and a docker-compose.yml.
YAML

services:
  fastmail-gatekeeper:
    build: .
    ports:
      - "8080:8000"
    env_file: .env
    restart: unless-stopped

5. Security & Safety Requirements

    Validation: The agent must ensure the body and to fields are sanitized.

    Statelessness: No SQLite database should be used. The ai_outgoing folder in Fastmail is the only source of truth for pending approvals.

    Visibility: The "Delete" tool must be explicitly named trash_email in the AI's tool definition so the LLM understands it is not a permanent destruction.

Verification Checklist for the Agent

    [ ] Does the "Delete" function call JMAP destroy? (Answer must be NO).

    [ ] Is the PIN stored in the Fastmail draft metadata? (Answer must be YES).

    [ ] Is there an authentication check on the API endpoints? (Answer must be YES).