#!/usr/bin/env python3
"""Re-authenticate Google Calendar. Run this once to get a fresh token."""
import json
import pickle
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

CONFIG_PATH = Path.home() / ".nanobot" / "config.json"
TOKEN_PATH = Path.home() / ".nanobot" / "google_calendar_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

config = json.loads(CONFIG_PATH.read_text())
cal_cfg = config["tools"]["google_calendar"]

client_config = {
    "installed": {
        "client_id": cal_cfg["clientId"],
        "client_secret": cal_cfg["clientSecret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

with open(TOKEN_PATH, "wb") as f:
    pickle.dump(creds, f)

print(f"✓ Token saved to {TOKEN_PATH}")
