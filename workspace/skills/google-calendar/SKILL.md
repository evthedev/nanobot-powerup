---
name: google-calendar
description: Read and write Google Calendar events for the owner.
---

# Google Calendar Skill

List, create, and delete Google Calendar events.

## Usage

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.nanobot/workspace/skills/google-calendar'))
from google_calendar_helper import list_events, create_event, delete_event
```

### List upcoming events
```python
events = list_events(max_results=10, calendar_id='euveng@gmail.com')
for e in events:
    print(e['start'], e['summary'])
```

**Return schema** — each event is a plain dict with these keys. Do NOT call `.get()` on the values, they are already extracted strings:
```python
{
    "id":          "abc123...",            # string
    "summary":     "Team standup",         # string
    "start":       "2026-03-01T09:00:00+08:00",  # string — already extracted, NOT a dict
    "end":         "2026-03-01T09:30:00+08:00",  # string — already extracted, NOT a dict
    "location":    "Conference Room B",    # string or None
    "description": "Weekly sync",          # string or None
}
```

Correct usage:
```python
for e in events:
    print(e['start'], e['summary'])        # ✅ start is a plain string
    # print(e['start'].get('dateTime'))    # ❌ WRONG — start is not a dict
```

### Create an event
```python
link, event_id = create_event(
    summary="Meeting",
    start_dt="2026-02-22T09:00:00+08:00",
    end_dt="2026-02-22T10:00:00+08:00",
    description="Weekly sync",
    calendar_id="euveng@gmail.com"
)
```

### Delete an event
```python
delete_event(event_id, calendar_id="euveng@gmail.com")
```

## Notes
- Credentials are in `~/.nanobot/config.json` under `tools.google_calendar` — tokens are auto-refreshed
- Default calendar_id: `euveng@gmail.com` # NOTE TO PARAMETRISE THIS
