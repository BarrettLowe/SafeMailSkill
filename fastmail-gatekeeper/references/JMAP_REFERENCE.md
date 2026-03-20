# JMAP Reference

Quick reference for JMAP email properties and filter options used with
the `/v1/jmap` proxy endpoint.

## Email/get — useful `properties`

| Property | Type | Notes |
|---|---|---|
| `id` | string | Opaque message ID |
| `threadId` | string | Thread this message belongs to |
| `mailboxIds` | object | Map of `{mailboxId: true}` |
| `keywords` | object | Map of `{keyword: true}`; e.g. `"$seen"`, `"$flagged"`, `"$draft"` |
| `subject` | string | Email subject |
| `from` | EmailAddress[] | `[{"name":"...", "email":"..."}]` |
| `to` | EmailAddress[] | Recipients |
| `cc` | EmailAddress[] | CC recipients |
| `replyTo` | EmailAddress[] | Reply-to addresses |
| `sentAt` | UTCDate | Date in message headers |
| `receivedAt` | UTCDate | Date server received the message |
| `size` | int | Bytes |
| `preview` | string | First ~256 chars of plain text |
| `textBody` | BodyPart[] | List of plain-text body parts |
| `htmlBody` | BodyPart[] | List of HTML body parts |
| `bodyValues` | object | Map of `{partId: {value, charset, ...}}` |

To retrieve body content, include `"fetchTextBodyValues": true` and
optionally `"maxBodyValueBytes": 32768`. Access the text via:
`bodyValues[textBody[0].partId].value`.

---

## Email/query — `filter` object

| Field | Description |
|---|---|
| `inMailbox` | Restrict to a specific mailbox ID |
| `inMailboxOtherThan` | Exclude a list of mailbox IDs |
| `text` | Full-text search (subject + from + to + body) |
| `from` | Partial match on sender address |
| `to` | Partial match on any recipient address |
| `cc` | Partial match on CC address |
| `subject` | Partial match on subject |
| `body` | Full-text search in body only |
| `hasKeyword` | Only messages that have this keyword |
| `notKeyword` | Only messages that do NOT have this keyword |
| `after` | Received after this UTC date-time (ISO 8601) |
| `before` | Received before this UTC date-time (ISO 8601) |
| `minSize` | Minimum size in bytes |
| `maxSize` | Maximum size in bytes |

### Combining filters

Use `operator` + `conditions` for AND/OR/NOT:
```json
{
  "operator": "AND",
  "conditions": [
    {"inMailbox": "<INBOX_ID>"},
    {"notKeyword": "$seen"}
  ]
}
```

### `sort` options

```json
"sort": [
  {"property": "receivedAt", "isAscending": false},
  {"property": "subject",    "isAscending": true}
]
```

Common sort properties: `receivedAt`, `sentAt`, `subject`, `from`, `size`.

---

## Common JMAP keywords

| Keyword | Meaning |
|---|---|
| `$seen` | Read |
| `$answered` | Replied |
| `$flagged` | Starred / important |
| `$draft` | Draft (not yet sent) |
| `$forwarded` | Forwarded |
| `$junk` | Spam |
| `$notjunk` | Not spam |

---

## Thread/get

`Thread/get` returns an array of `threadId` objects, each with an `emailIds`
list in chronological order. Chain it with `Email/get` via a back-reference:

```json
["Thread/get", {"ids": ["<THREAD_ID>"]}, "c1"],
["Email/get", {
  "#ids": {"resultOf": "c1", "name": "Thread/get", "path": "/list/*/emailIds"},
  "properties": ["id", "subject", "from", "receivedAt", "preview"]
}, "c2"]
```

---

## Blocked operations (enforced by the gatekeeper server)

These will always return HTTP 403:

- `Email/destroy` — permanent deletion
- `Mailbox/destroy` — folder deletion
- `Thread/destroy` — thread deletion
- `EmailSubmission/set` — direct send (use `/v1/send` + `/v1/approve`)
- `Identity/set` — modifying send-from identities
- `VacationResponse/set` — modifying vacation responder
- `SieveScript/set` / `SieveScript/validate` — modifying filter rules
- `Email/set` updates where `mailboxIds` is `{}` or `null`
