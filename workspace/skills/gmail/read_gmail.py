#!/usr/bin/env python3
"""
Read/search Gmail and download attachments.

USAGE:
  python3 read_gmail.py search "in:sent to:support@pswenergy.com.au" --max 5
  python3 read_gmail.py search "in:all PSW" --max 10
  python3 read_gmail.py list --max 20
  python3 read_gmail.py read <message_id>
  python3 read_gmail.py download <message_id> <attachment_id> --out /path/to/save.jpg
"""
import argparse, base64, json, os, re, sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".nanobot/config.json"
_SSL_VERIFY = os.environ.get("NANOBOT_SSL_VERIFY", "true").lower() not in ("false", "0", "no")
if not _SSL_VERIFY:
    import ssl; ssl._create_default_https_context = ssl._create_unverified_context  # noqa
    try: import urllib3; urllib3.disable_warnings()
    except ImportError: pass


def _build_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import requests as rlib

    cfg = json.loads(CONFIG_PATH.read_text())
    gc = cfg.get("tools", {}).get("google_calendar", {})
    td = gc.get("tokens", {})
    if isinstance(td, str): td = json.loads(td)
    if not td.get("refresh_token"):
        print("❌ No Google OAuth tokens. Re-authenticate via dashboard → Settings → Google Auth.")
        sys.exit(1)

    scopes = td.get("scope", ""); scopes = scopes.split() if isinstance(scopes, str) else list(scopes)
    session = rlib.Session()
    if not _SSL_VERIFY: session.verify = False

    creds = Credentials(
        token=td.get("access_token"), refresh_token=td.get("refresh_token"),
        token_uri=td.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=gc.get("clientId") or td.get("client_id", ""),
        client_secret=gc.get("clientSecret") or td.get("client_secret", ""),
        scopes=scopes or None,
    )
    if not creds.valid:
        creds.refresh(Request(session=session))
        cfg["tools"]["google_calendar"]["tokens"].update({
            "access_token": creds.token, "refresh_token": creds.refresh_token,
            "scope": " ".join(creds.scopes or []),
        })
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_body(payload) -> str:
    mime = payload.get("mimeType", ""); data = payload.get("body", {}).get("data", "")
    if data and mime in ("text/plain", "text/html"):
        text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if mime == "text/html":
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
            text = re.sub(r"</p>", "\n\n", text, flags=re.I)
            text = re.sub(r"<[^>]+>", "", text).strip()
        return text
    parts = payload.get("parts", [])
    plain = next((p for p in parts if p.get("mimeType") == "text/plain"), None)
    for part in ([plain] if plain else parts):
        if part and (r := _decode_body(part)): return r
    return ""


def _list_attachments(payload, results=None) -> list:
    """Recursively collect all attachments from a message payload."""
    if results is None: results = []
    body = payload.get("body", {})
    filename = payload.get("filename", "")
    if filename and body.get("attachmentId"):
        results.append({
            "filename": filename,
            "mimeType": payload.get("mimeType", ""),
            "size": body.get("size", 0),
            "attachmentId": body["attachmentId"],
        })
    for part in payload.get("parts", []):
        _list_attachments(part, results)
    return results


def _fmt(msg: dict) -> dict:
    h = {x["name"].lower(): x["value"] for x in msg["payload"]["headers"]}
    body = _decode_body(msg["payload"])
    attachments = _list_attachments(msg["payload"])
    return {
        "id": msg["id"],
        "from": h.get("from", ""), "to": h.get("to", ""),
        "subject": h.get("subject", ""), "date": h.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body[:4000] + ("\n[... truncated]" if len(body) > 4000 else ""),
        "attachments": attachments,
    }


def _print(r: dict, idx: int = None):
    prefix = f"[{idx}] " if idx else ""
    print("─" * 60)
    print(f"{prefix}MESSAGE_ID: {r['id']}")
    print(f"    From:    {r['from']}")
    print(f"    To:      {r['to']}")
    print(f"    Subject: {r['subject']}")
    print(f"    Date:    {r['date']}")
    if r["attachments"]:
        print(f"    Attachments:")
        for a in r["attachments"]:
            print(f"      DOWNLOAD: message_id={r['id']} attachment_id={a['attachmentId']} filename={a['filename']} size={a['size']}B")
    print(f"\n    Body:\n{r['body']}\n")


def cmd_search(query: str, max_results: int):
    svc = _build_service()
    resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    msgs = resp.get("messages", [])
    if not msgs: print(f"No emails found for: {query!r}"); return
    print(f"Found {len(msgs)} email(s) for: {query!r}\n")
    for i, m in enumerate(msgs, 1):
        full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
        _print(_fmt(full), i)


def cmd_fetch_attachment(query: str, out_dir: str):
    """Search, find the first email with an image attachment, download it. Atomic."""
    svc = _build_service()
    resp = svc.users().messages().list(userId="me", q=query, maxResults=10).execute()
    msgs = resp.get("messages", [])
    if not msgs: print(f"No emails found for: {query!r}"); sys.exit(1)

    for m in msgs:
        full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
        r = _fmt(full)
        for att in r["attachments"]:
            if att["mimeType"].startswith("image/"):
                out_path = str(Path(out_dir) / att["filename"])
                cmd_download(r["id"], att["attachmentId"], out_path)
                print(f"MESSAGE_ID: {r['id']}")
                print(f"From:    {r['from']}")
                print(f"Subject: {r['subject']}")
                print(f"Date:    {r['date']}")
                print(f"FILE:    {out_path}")
                return
    print("No image attachments found in matching emails.")
    sys.exit(1)


def cmd_read(message_id: str):
    svc = _build_service()
    full = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    _print(_fmt(full))


def cmd_download(message_id: str, attachment_id: str, out_path: str):
    svc = _build_service()
    att = svc.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    data = base64.urlsafe_b64decode(att["data"] + "==")
    Path(out_path).write_bytes(data)
    print(f"✅ Saved {len(data)} bytes → {out_path}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--max", type=int, default=5)
    l = sub.add_parser("list");   l.add_argument("--max", type=int, default=10)
    r = sub.add_parser("read");   r.add_argument("message_id")
    d = sub.add_parser("download"); d.add_argument("message_id"); d.add_argument("attachment_id")
    d.add_argument("--out", required=True, help="Absolute path to save the file")
    fa = sub.add_parser("fetch-attachment", help="Search and download first image attachment atomically")
    fa.add_argument("query"); fa.add_argument("--out-dir", default="/root/.nanobot/workspace/screenshots")

    args = p.parse_args()
    if   args.cmd == "search":           cmd_search(args.query, args.max)
    elif args.cmd == "list":             cmd_search("in:inbox", args.max)
    elif args.cmd == "read":             cmd_read(args.message_id)
    elif args.cmd == "download":         cmd_download(args.message_id, args.attachment_id, args.out)
    elif args.cmd == "fetch-attachment": cmd_fetch_attachment(args.query, args.out_dir)
    else:                                p.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
