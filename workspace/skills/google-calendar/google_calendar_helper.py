"""Google Calendar helper — loads credentials from ~/.nanobot/config.json (tools.google_calendar)."""
import json
from pathlib import Path
from datetime import datetime, timezone

CONFIG_PATH = Path.home() / ".nanobot" / "config.json"


def _read_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    # Credentials live in ~/.nanobot/config.json under tools.google_calendar — always read here first.
    config = _read_config()
    gc_cfg = config.get("tools", {}).get("google_calendar", {})

    client_id = gc_cfg.get("clientId", "")
    client_secret = gc_cfg.get("clientSecret", "")
    token_data = gc_cfg.get("tokens", {})

    if not token_data or not token_data.get("refresh_token"):
        raise RuntimeError(
            "No Google Calendar tokens found in ~/.nanobot/config.json under tools.google_calendar.tokens. "
            "Please re-authenticate via the dashboard."
        )

    scopes = token_data.get("scope", "")
    scopes = scopes.split() if isinstance(scopes, str) else scopes

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
        # Write refreshed tokens back to config.json so the source of truth stays current.
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


def _build_service(api="calendar", version="v3"):
    from googleapiclient.discovery import build
    creds = _load_credentials()
    return build(api, version, credentials=creds)


def list_events(max_results=20, calendar_id="primary", time_min=None):
    """List upcoming calendar events."""
    service = _build_service()
    if time_min is None:
        time_min = datetime.now(timezone.utc).isoformat()
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = result.get("items", [])
    simplified = []
    for e in events:
        start = e.get("start", {})
        simplified.append({
            "id": e.get("id"),
            "summary": e.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": (e.get("end", {}).get("dateTime") or e.get("end", {}).get("date")),
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return simplified


def create_event(summary, start_dt, end_dt, description=None, location=None, calendar_id="primary"):
    """Create a calendar event. start_dt/end_dt are ISO 8601 strings."""
    service = _build_service()
    body = {
        "summary": summary,
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    return event.get("htmlLink"), event.get("id")


def delete_event(event_id, calendar_id="primary"):
    """Delete a calendar event by ID."""
    service = _build_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return True
