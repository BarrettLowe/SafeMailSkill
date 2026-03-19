"""JMAP client for Fastmail interactions."""

import logging
import random
import string
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Keyword prefixes embedded into JMAP drafts for stateless PIN tracking.
# Keywords must be lowercase ASCII; the prefixes include a leading '$' which
# JMAP implementations treat as a user-defined flag.
_PIN_KEYWORD_PREFIX = "$ai_pin_"
_TS_KEYWORD_PREFIX = "$ai_ts_"


class JMAPError(Exception):
    """Raised when a JMAP call fails."""


class JMAPClient:
    """Thin JMAP client that handles session bootstrapping and method calls."""

    def __init__(self) -> None:
        self._session: Optional[dict] = None
        self._account_id: Optional[str] = None
        self._headers = {
            "Authorization": f"Bearer {settings.fastmail_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Session / bootstrap
    # ------------------------------------------------------------------

    def _get_session(self) -> dict:
        if self._session is None:
            resp = httpx.get(
                settings.fastmail_session_url, headers=self._headers, timeout=10
            )
            resp.raise_for_status()
            self._session = resp.json()
            self._account_id = self._session["primaryAccounts"]["urn:ietf:params:jmap:mail"]
        return self._session

    def _get_api_url(self) -> str:
        session = self._get_session()
        return session.get("apiUrl", settings.fastmail_api_url)

    def _account(self) -> str:
        self._get_session()
        if self._account_id is None:
            raise JMAPError("Unable to determine JMAP account ID")
        return self._account_id

    # ------------------------------------------------------------------
    # Low-level JMAP invocation
    # ------------------------------------------------------------------

    def _call(self, method_calls: list) -> dict:
        payload = {
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
            "methodCalls": method_calls,
        }
        resp = httpx.post(
            self._get_api_url(), json=payload, headers=self._headers, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        return data

    # ------------------------------------------------------------------
    # Mailbox helpers
    # ------------------------------------------------------------------

    def _get_mailbox_id(self, name: str) -> str:
        """Return the mailbox ID for *name*, creating it if absent."""
        data = self._call(
            [
                [
                    "Mailbox/get",
                    {"accountId": self._account(), "ids": None},
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Mailbox/get returned no responses")

        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Mailbox/get error: {resp_args}")

        mailboxes: list[dict] = resp_args.get("list", [])
        for mb in mailboxes:
            if mb.get("name", "").lower() == name.lower():
                return mb["id"]

        # Folder doesn't exist – create it
        return self._create_mailbox(name)

    def _create_mailbox(self, name: str) -> str:
        data = self._call(
            [
                [
                    "Mailbox/set",
                    {
                        "accountId": self._account(),
                        "create": {"new_mb": {"name": name}},
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Mailbox/set returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Mailbox/set error: {resp_args}")
        created = resp_args.get("created", {}).get("new_mb")
        if not created:
            raise JMAPError(f"Failed to create mailbox '{name}'")
        return created["id"]

    # ------------------------------------------------------------------
    # Email helpers
    # ------------------------------------------------------------------

    def _get_email(self, email_id: str) -> dict:
        data = self._call(
            [
                [
                    "Email/get",
                    {
                        "accountId": self._account(),
                        "ids": [email_id],
                        "properties": ["id", "mailboxIds"],
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Email/get returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Email/get error: {resp_args}")
        emails = resp_args.get("list", [])
        if not emails:
            raise JMAPError(f"Email '{email_id}' not found")
        return emails[0]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def shadow_delete(self, email_id: str) -> None:
        """Move *email_id* to the ai_trash folder (no permanent deletion)."""
        trash_id = self._get_mailbox_id(settings.ai_trash_folder)
        email = self._get_email(email_id)
        current_mailboxes: dict = email.get("mailboxIds", {})

        new_mailboxes = {trash_id: True}
        patch: dict = {}
        for mb_id in current_mailboxes:
            patch[f"mailboxIds/{mb_id}"] = None
        patch[f"mailboxIds/{trash_id}"] = True

        data = self._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": self._account(),
                        "update": {email_id: patch},
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Email/set returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Email/set error: {resp_args}")
        updated = resp_args.get("updated", {})
        if email_id not in updated:
            not_updated = resp_args.get("notUpdated", {})
            raise JMAPError(
                f"Failed to move email to ai_trash: {not_updated.get(email_id)}"
            )

    def create_outgoing_draft(
        self, to: str, subject: str, body: str, pin: str
    ) -> str:
        """Create a draft in ai_outgoing with the PIN stored as a keyword."""
        outgoing_id = self._get_mailbox_id(settings.ai_outgoing_folder)
        from_identity = self._get_identity()

        # Store PIN as a keyword so we can query it later without needing a
        # local database.
        pin_keyword = f"{_PIN_KEYWORD_PREFIX}{pin}"
        # Also embed the creation timestamp so we can enforce expiry.
        ts = int(datetime.now(timezone.utc).timestamp())
        ts_keyword = f"{_TS_KEYWORD_PREFIX}{ts}"

        email_body = {
            "mailboxIds": {outgoing_id: True},
            "keywords": {
                "$draft": True,
                pin_keyword: True,
                ts_keyword: True,
            },
            "from": [{"email": from_identity}],
            "to": [{"email": to}],
            "subject": subject,
            "bodyValues": {
                "body": {
                    "value": body,
                    "charset": "utf-8",
                }
            },
            "textBody": [{"partId": "body", "type": "text/plain"}],
        }

        data = self._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": self._account(),
                        "create": {"draft": email_body},
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Email/set returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Email/set error: {resp_args}")
        created = resp_args.get("created", {}).get("draft")
        if not created:
            raise JMAPError("Failed to create draft in ai_outgoing")
        return created["id"]

    def _get_identity(self) -> str:
        """Return the primary sender identity address."""
        data = self._call(
            [
                [
                    "Identity/get",
                    {"accountId": self._account(), "ids": None},
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Identity/get returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Identity/get error: {resp_args}")
        identities = resp_args.get("list", [])
        if not identities:
            raise JMAPError("No identities found in Fastmail account")
        return identities[0]["email"]

    def find_draft_by_pin(self, pin: str) -> Optional[dict]:
        """Search ai_outgoing for a draft whose keywords contain the given PIN.

        Returns the email dict (with keywords) or None if not found.
        """
        outgoing_id = self._get_mailbox_id(settings.ai_outgoing_folder)
        pin_keyword = f"{_PIN_KEYWORD_PREFIX}{pin}"

        data = self._call(
            [
                [
                    "Email/query",
                    {
                        "accountId": self._account(),
                        "filter": {
                            "inMailbox": outgoing_id,
                            "hasKeyword": pin_keyword,
                        },
                        "limit": 1,
                    },
                    "0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": self._account(),
                        "#ids": {
                            "resultOf": "0",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "keywords",
                            "to",
                            "subject",
                            "bodyValues",
                            "textBody",
                        ],
                        "fetchTextBodyValues": True,
                    },
                    "1",
                ],
            ]
        )
        responses = data.get("methodResponses", [])
        # responses[0] is Email/query, responses[1] is Email/get
        if len(responses) < 2:
            return None
        get_name, get_args, _ = responses[1]
        if get_name == "error":
            raise JMAPError(f"Email/get error: {get_args}")
        emails = get_args.get("list", [])
        return emails[0] if emails else None

    def send_draft(self, draft_id: str) -> None:
        """Submit *draft_id* via EmailSubmission/set and delete the draft."""
        data = self._call(
            [
                [
                    "EmailSubmission/set",
                    {
                        "accountId": self._account(),
                        "create": {
                            "submission": {
                                "emailId": draft_id,
                                "identityId": self._get_submission_identity(),
                            }
                        },
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("EmailSubmission/set returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"EmailSubmission/set error: {resp_args}")
        created = resp_args.get("created", {}).get("submission")
        if not created:
            not_created = resp_args.get("notCreated", {}).get("submission")
            raise JMAPError(f"Failed to submit email: {not_created}")

        # Clean up the draft from ai_outgoing
        self._delete_email(draft_id)

    def _get_submission_identity(self) -> str:
        """Return the identity ID suitable for EmailSubmission."""
        data = self._call(
            [
                [
                    "Identity/get",
                    {"accountId": self._account(), "ids": None},
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Identity/get returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Identity/get error: {resp_args}")
        identities = resp_args.get("list", [])
        if not identities:
            raise JMAPError("No identities found")
        return identities[0]["id"]

    def _delete_email(self, email_id: str) -> None:
        """Permanently destroy an email (used only for sent drafts)."""
        data = self._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": self._account(),
                        "destroy": [email_id],
                    },
                    "0",
                ]
            ]
        )
        responses = data.get("methodResponses", [])
        if not responses:
            raise JMAPError("Email/set returned no responses")
        resp_name, resp_args, _ = responses[0]
        if resp_name == "error":
            raise JMAPError(f"Email/set (destroy) error: {resp_args}")


def generate_pin(length: int = 4) -> str:
    """Generate a random numeric PIN."""
    return "".join(random.choices(string.digits, k=length))
