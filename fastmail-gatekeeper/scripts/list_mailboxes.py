#!/usr/bin/env python3
"""
List all Fastmail mailbox IDs so you can populate AI_TRASH_ID and AI_OUTGOING_ID.

Usage:
    FASTMAIL_TOKEN=your-token python scripts/list_mailboxes.py
"""

import json
import os
import sys
import urllib.request

TOKEN = os.environ.get("FASTMAIL_TOKEN")
if not TOKEN:
    sys.exit("Error: FASTMAIL_TOKEN environment variable is not set.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# ── 1. Fetch JMAP session ─────────────────────────────────────────────────────
req = urllib.request.Request(
    "https://api.fastmail.com/jmap/session",
    headers=HEADERS,
)
try:
    with urllib.request.urlopen(req) as r:
        session = json.load(r)
except urllib.error.HTTPError as exc:
    sys.exit(f"Error fetching JMAP session (HTTP {exc.code}). Check FASTMAIL_TOKEN.")

api_url: str = session["apiUrl"]
account_id: str = session["primaryAccounts"]["urn:ietf:params:jmap:mail"]

# ── 2. Fetch mailboxes ────────────────────────────────────────────────────────
payload = json.dumps(
    {
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        "methodCalls": [
            ["Mailbox/get", {"accountId": account_id, "ids": None}, "c1"]
        ],
    }
).encode()

req = urllib.request.Request(api_url, data=payload, headers=HEADERS, method="POST")
with urllib.request.urlopen(req) as r:
    result = json.load(r)

mailboxes: list = result["methodResponses"][0][1]["list"]
mailboxes.sort(key=lambda m: (m.get("role") or "z", m["name"].lower()))

# ── 3. Print table ────────────────────────────────────────────────────────────
print(f"Account ID : {account_id}\n")
print(f"{'NAME':<35} {'ROLE':<15} ID")
print("-" * 90)
for mb in mailboxes:
    role = mb.get("role") or ""
    marker = " ← AI_TRASH_ID?" if role == "trash" else ""
    print(f"{mb['name']:<35} {role:<15} {mb['id']}{marker}")
