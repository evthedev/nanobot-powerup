"""Gmail helper — reuses existing google_calendar credentials from ~/.nanobot/config.json."""
import json
import base64
import re
from pathlib import Path
from datetime import datetime, timezone

CONFIG_PATH = Path.home() / ".nanobot" / "config.json"


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    config = json.loads(CONFIG_PATH.read_text())
    gc_cfg = config.get("tools", {}).get("google_calendar", {})

    client_id = gc_cfg.get("clientId", "")
    client_secret = gc_cfg.get("clientSecret", "")
    token_data = gc_cfg.get("tokens", {})

    if not token_data or not token_data.get("refresh_token"):
        raise RuntimeError(
            "No Google tokens found in ~/.nanobot/config.json under tools.google_calendar.tokens. "
            "Re-authenticate via the nanobot dashboard."
        )

    scopes = token_data.get("scope", "")
    scopes = scopes.split() if isinstance(scopes, str) else scopes

    if not any("gmail" in s for s in scopes):
        raise RuntimeError(
            "Gmail scope not present in current token. "
            "Re-authenticate via the nanobot dashboard to add gmail.readonly."
        )

    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id or token_data.get("client_id", ""),
        client_secret=client_secret or token_data.get("client_secret", ""),
        scopes=scopes,
    )

    if not creds.valid:
        creds.refresh(Request())
        config["tools"]["google_calendar"]["tokens"].update({
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scope": " ".join(creds.scopes) if creds.scopes else "",
        })
        CONFIG_PATH.write_text(json.dumps(config, indent=2))

    return creds


def _build_gmail():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=_load_credentials())


def _decode_body(payload) -> str:
    """Recursively extract plain-text body from a message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _decode_body(part)
            if text:
                return text
    return ""


def _parse_headers(headers: list) -> dict:
    return {h["name"].lower(): h["value"] for h in headers}


def list_emails(max_results: int = 20, query: str = "", label: str = "INBOX") -> list[dict]:
    """
    List emails from Gmail.

    Args:
        max_results: Number of emails to return (default 20, max 500).
        query: Gmail search query e.g. 'from:someone@example.com', 'is:unread', 'subject:invoice'.
        label: Gmail label to filter by (default 'INBOX'). Use '' for all mail.

    Returns:
        List of dicts with keys: id, thread_id, subject, from, to, date, snippet, body.
    """
    svc = _build_gmail()
    q = query
    if label and not query:
        q = f"label:{label}"
    elif label and query:
        q = f"label:{label} {query}"

    result = svc.users().messages().list(
        userId="me", q=q, maxResults=min(max_results, 500)
    ).execute()

    messages = result.get("messages", [])
    emails = []

    for msg_stub in messages:
        msg = svc.users().messages().get(
            userId="me", id=msg_stub["id"], format="full"
        ).execute()

        headers = _parse_headers(msg.get("payload", {}).get("headers", []))
        body = _decode_body(msg.get("payload", {}))

        emails.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "subject": headers.get("subject", "(no subject)"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "body": body.strip(),
            "labels": msg.get("labelIds", []),
        })

    return emails


def get_email(message_id: str) -> dict:
    """Fetch a single email by its Gmail message ID."""
    svc = _build_gmail()
    msg = svc.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = _parse_headers(msg.get("payload", {}).get("headers", []))
    body = _decode_body(msg.get("payload", {}))

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "subject": headers.get("subject", "(no subject)"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body.strip(),
        "labels": msg.get("labelIds", []),
    }


def search_emails(query: str, max_results: int = 20) -> list[dict]:
    """Search emails using a Gmail query string. Alias for list_emails with a query."""
    return list_emails(max_results=max_results, query=query, label="")


def get_unread_count(label: str = "INBOX") -> int:
    """Return the number of unread messages in a label."""
    svc = _build_gmail()
    result = svc.users().labels().get(userId="me", id=label).execute()
    return result.get("messagesUnread", 0)
