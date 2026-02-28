#!/usr/bin/env python3
"""Standalone script: list upcoming Google Calendar events.
Deployed to /root/.nanobot/workspace/skills/google-calendar/list-calendar.py"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from google_calendar_helper import list_events

events = list_events(max_results=30)
print(json.dumps(events, indent=2, ensure_ascii=False))
