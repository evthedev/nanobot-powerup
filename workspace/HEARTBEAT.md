# Heartbeat Tasks

<!--
Rotating heartbeat — each 30-min tick runs the single most overdue check.
State tracked in: ~/.nanobot/workspace/heartbeat-state.json

DELIVERY RULE: Do NOT call message(). Include any notification text in your
final reply. The system delivers it. If nothing is actionable, reply HEARTBEAT_OK.
-->

## Active Tasks

- [ ] Run rotating check protocol below

---

## Rotating Check Protocol

### Step 1 — Load state and get Perth time

```
exec("cat ~/.nanobot/workspace/heartbeat-state.json 2>/dev/null || echo '{}'")
exec("python3 -c \"from datetime import datetime; import pytz; now=datetime.now(pytz.timezone('Australia/Perth')); print(int(now.timestamp()), now.hour)\"")
```

Output: `<unix_timestamp> <hour_0_to_23>`

### Step 2 — Decide which check to run

Priority order:

1. **calendar** — if `(now - last_calendar) >= 7200` AND `7 <= hour <= 22`
2. **todos** — if `(now - last_todos) >= 1800`
3. Neither condition met → reply `HEARTBEAT_OK`, stop here.

Use `0` for any key missing from the state file (treat as never run).

---

### `calendar` check

```
exec("python3 ~/.nanobot/workspace/skills/google-calendar/list-calendar.py")
```

Parse the JSON for events starting within the next **3 hours**.

- **Found events** → include a concise summary in your final reply (event name, time, one-line context).
- **No events within 3 hours** → reply `HEARTBEAT_OK`.

Update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['calendar']=int(time.time()); p.write_text(json.dumps(s))\"")
```

---

### `todos` check

```
exec("grep -A 200 '## Todos' ~/.nanobot/workspace/memory/MEMORY.md")
```

- **Found unchecked lines (`- [ ] ...`)** → include a short bulleted list in your final reply.
- **No `## Todos` section, or section exists but no unchecked items** → reply `HEARTBEAT_OK`. Do NOT ask questions. Do NOT offer to create anything.

Update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['todos']=int(time.time()); p.write_text(json.dumps(s))\"")
```

---

### Final reply

- Something to notify → reply with the notification text (no preamble, no questions).
- Nothing actionable → reply `HEARTBEAT_OK`.
