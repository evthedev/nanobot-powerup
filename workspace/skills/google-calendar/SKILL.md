---
name: google-calendar
description: Read and write Google Calendar events for the owner.
---

# Google Calendar Skill

List, create, and delete Google Calendar events.

## Usage

```python
import sys
sys.path.insert(0, str(Path.home() / '.nanobot/workspace/skills/google-calendar'))
from google_calendar_helper import list_events, create_event, delete_event
```

### List upcoming events
```python
events = list_events(max_results=10, calendar_id='euveng@gmail.com')
for e in events:
    print(e['start'], e['summary'])
```

### Create an event
```python
link, event_id = create_event(
    summary="Meeting",
    start_dt="2026-02-22T09:00:00Z",
    end_dt="2026-02-22T10:00:00Z",
    description="Weekly sync",
    calendar_id="euveng@gmail.com"
)
```

### Delete an event
```python
delete_event(event_id, calendar_id="euveng@gmail.com")
```

## Notes
- Token is at ~/.nanobot/google_calendar_token.json (auto-refreshed)
- Credentials are in ~/.nanobot/config.json under tools.google_calendar
- Default calendar_id: euveng@gmail.com
