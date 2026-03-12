---
name: google-calendar
description: Read and write Google Calendar events for the owner.
---

# Google Calendar Skill

List, create, and delete Google Calendar events via `google_calendar_helper.py`.

## Listing events — use the ready-made script

**Do NOT write a new list script.** Run the existing one directly:

```bash
python3 ~/.nanobot/workspace/skills/google-calendar/list-calendar.py
```

Output: JSON array of events. Each event has: `id`, `summary`, `start`, `end`, `location`, `description`.
These are plain strings — do NOT call `.get()` on them, they are already extracted.

---

## Creating or deleting events — use the helper as a library

For create and delete, write a short script that imports the helper. **Do NOT re-implement the API logic** — import it:

```python
import sys
sys.path.insert(0, '/root/.nanobot/workspace/skills/google-calendar')
from google_calendar_helper import create_event, delete_event

# Create
link, event_id = create_event(
    summary="Meeting",
    start_dt="2026-02-22T09:00:00+08:00",
    end_dt="2026-02-22T10:00:00+08:00",
    description="Weekly sync",
    calendar_id="euveng@gmail.com"
)
print(link, event_id)

# Delete
delete_event(event_id="abc123...", calendar_id="euveng@gmail.com")
print("deleted")
```

Save to `/root/.nanobot/workspace/my_calendar_task.py` and run:
```bash
python3 /root/.nanobot/workspace/my_calendar_task.py
```

---

## Notes
- Credentials are in `~/.nanobot/config.json` under `tools.google_calendar` — tokens are auto-refreshed
- Default calendar: `euveng@gmail.com`
- Timezone: use ISO 8601 with offset, e.g. `2026-03-01T09:00:00+08:00`
- `start` and `end` in list output are plain strings, not dicts
