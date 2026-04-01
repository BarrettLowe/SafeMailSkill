#!/usr/bin/env python3
"""
Gatekeeper CLI — agent helper for the Fastmail Gatekeeper server.

Reads GATEKEEPER_API_KEY from the environment and always prints JSON to stdout.

Usage:
    python scripts/gatekeeper.py <command> [args...]

Commands:
    list-mailboxes
    list-emails     [<mailbox_name>] [--limit N] [--search TEXT] [--from ADDR]
                                 [--subject TEXT] [--unread] [--after ISO] [--before ISO]
    get-email       <message_id>
    get-thread      <thread_id>
    list-attachments <message_id>
    download        <message_id> <filename> [--save PATH]
    trash           <message_id>
    move            <message_id> <mailbox_name>
    mark-read       <message_id>
    mark-unread     <message_id>
    flag            <message_id>
    unflag          <message_id>
    send            <to> <subject> <body>
    approve         <pin>
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("GATEKEEPER_BASE_URL", "http://127.0.0.1:8080")
API_KEY  = os.environ.get("GATEKEEPER_API_KEY", "")


def _headers():
    if not API_KEY:
        _die("GATEKEEPER_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=_headers(),
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.load(exc)
        except Exception:
            payload = {"error": exc.reason}
        _die_json(exc.code, payload)


def _jmap(method_calls: list) -> dict:
    return _request("POST", "/v1/jmap", {"methodCalls": method_calls})


def _die(msg: str):
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _die_json(code: int, payload: dict):
    print(json.dumps({"http_status": code, **payload}), file=sys.stderr)
    sys.exit(1)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list_mailboxes(_args):
    result = _request("GET", "/v1/mailboxes")
    print(json.dumps(result, indent=2))


def cmd_list_emails(args):
    filt: dict = {}
    if args.mailbox_name: filt["inMailbox"] = args.mailbox_name
    if args.search:       filt["text"]      = args.search
    if args.from_:    filt["from"]        = args.from_
    if args.subject:  filt["subject"]     = args.subject
    if args.unread:   filt["notKeyword"]  = "$seen"
    if args.after:    filt["after"]       = args.after
    if args.before:   filt["before"]      = args.before

    result = _jmap([
        ["Email/query", {
            "filter": filt,
            "sort":   [{"property": "receivedAt", "isAscending": False}],
            "limit":  args.limit,
            "position": 0,
        }, "c1"],
        ["Email/get", {
            "#ids": {"resultOf": "c1", "name": "Email/query", "path": "/ids"},
            "properties": ["id", "threadId", "subject", "from", "to",
                           "receivedAt", "preview", "keywords"],
        }, "c2"],
    ])
    emails = result["methodResponses"][1][1].get("list", [])
    print(json.dumps(emails, indent=2))


def cmd_get_email(args):
    result = _jmap([
        ["Email/get", {
            "ids": [args.message_id],
            "properties": [
                "id", "threadId", "subject", "from", "to", "cc", "replyTo",
                "receivedAt", "keywords", "textBody", "bodyValues",
            ],
            "fetchTextBodyValues": True,
            "maxBodyValueBytes": 32768,
        }, "c1"],
    ])
    emails = result["methodResponses"][0][1].get("list", [])
    print(json.dumps(emails[0] if emails else {}, indent=2))


def cmd_get_thread(args):
    result = _jmap([
        ["Thread/get", {"ids": [args.thread_id]}, "c1"],
        ["Email/get", {
            "#ids": {
                "resultOf": "c1",
                "name": "Thread/get",
                "path": "/list/*/emailIds",
            },
            "properties": ["id", "subject", "from", "receivedAt", "preview", "keywords"],
        }, "c2"],
    ])
    emails = result["methodResponses"][1][1].get("list", [])
    print(json.dumps(emails, indent=2))


def cmd_list_attachments(args):
    result = _jmap([
        ["Email/get", {
            "ids": [args.message_id],
            "properties": ["attachments"],
        }, "c1"],
    ])
    emails = result["methodResponses"][0][1].get("list", [])
    attachments = emails[0].get("attachments") or [] if emails else []
    print(json.dumps(attachments, indent=2))


def cmd_download(args):
    result = _request("POST", "/v1/download", {
        "message_id": args.message_id,
        "filename":   args.filename,
    })
    if args.save and result.get("data"):
        raw = base64.b64decode(result["data"])
        with open(args.save, "wb") as fh:
            fh.write(raw)
        summary = {k: v for k, v in result.items() if k != "data"}
        summary["saved_to"] = args.save
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(result, indent=2))


def cmd_trash(args):
    result = _request("POST", "/v1/delete", {"message_id": args.message_id})
    print(json.dumps(result, indent=2))


def cmd_move(args):
    result = _jmap([
        ["Email/set", {
            "update": {
                args.message_id: {
                    "mailboxIds": {args.mailbox_name: True}
                }
            }
        }, "c1"],
    ])
    print(json.dumps(result["methodResponses"][0][1], indent=2))


def _set_keyword(message_id: str, keyword: str, value):
    result = _jmap([
        ["Email/set", {
            "update": {message_id: {f"keywords/{keyword}": value}}
        }, "c1"],
    ])
    print(json.dumps(result["methodResponses"][0][1], indent=2))


def cmd_mark_read(args):    _set_keyword(args.message_id, "$seen",    True)
def cmd_mark_unread(args):  _set_keyword(args.message_id, "$seen",    None)
def cmd_flag(args):         _set_keyword(args.message_id, "$flagged", True)
def cmd_unflag(args):       _set_keyword(args.message_id, "$flagged", None)


def cmd_send(args):
    result = _request("POST", "/v1/send", {
        "to":      args.to,
        "subject": args.subject,
        "body":    args.body,
    })
    print(json.dumps(result, indent=2))


def cmd_approve(args):
    result = _request("POST", "/v1/approve", {"pin": args.pin})
    print(json.dumps(result, indent=2))


# ── Argument parsing ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Gatekeeper CLI — returns JSON for every command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list-mailboxes")

    le = sub.add_parser("list-emails")
    le.add_argument("mailbox_name", nargs="?", default=None)
    le.add_argument("--limit",   type=int, default=20)
    le.add_argument("--search",  dest="search")
    le.add_argument("--from",    dest="from_")
    le.add_argument("--subject", dest="subject")
    le.add_argument("--unread",  action="store_true")
    le.add_argument("--after",   dest="after")
    le.add_argument("--before",  dest="before")

    ge = sub.add_parser("get-email")
    ge.add_argument("message_id")

    gt = sub.add_parser("get-thread")
    gt.add_argument("thread_id")

    la = sub.add_parser("list-attachments")
    la.add_argument("message_id")

    dl = sub.add_parser("download")
    dl.add_argument("message_id")
    dl.add_argument("filename")
    dl.add_argument("--save", dest="save", default=None, metavar="PATH",
                    help="Save decoded file to PATH instead of printing base64 JSON")

    tr = sub.add_parser("trash")
    tr.add_argument("message_id")

    mv = sub.add_parser("move")
    mv.add_argument("message_id")
    mv.add_argument("mailbox_name")

    for name in ("mark-read", "mark-unread", "flag", "unflag"):
        sp = sub.add_parser(name)
        sp.add_argument("message_id")

    sn = sub.add_parser("send")
    sn.add_argument("to")
    sn.add_argument("subject")
    sn.add_argument("body")

    ap = sub.add_parser("approve")
    ap.add_argument("pin")

    args = p.parse_args()
    dispatch = {
        "list-mailboxes":    cmd_list_mailboxes,
        "list-emails":       cmd_list_emails,
        "get-email":         cmd_get_email,
        "get-thread":        cmd_get_thread,
        "list-attachments":  cmd_list_attachments,
        "download":          cmd_download,
        "trash":             cmd_trash,
        "move":              cmd_move,
        "mark-read":         cmd_mark_read,
        "mark-unread":       cmd_mark_unread,
        "flag":              cmd_flag,
        "unflag":            cmd_unflag,
        "send":              cmd_send,
        "approve":           cmd_approve,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
