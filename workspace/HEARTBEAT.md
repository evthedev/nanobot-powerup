# Heartbeat Tasks

<!--
Rotating heartbeat — runs the most overdue check on each 30-min tick.
State tracked in: ~/.nanobot/workspace/heartbeat-state.json
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

The output is: `<unix_timestamp> <hour_0_to_23>`

### Step 2 — Decide which check to run

Use this priority order (check **calendar first**, then **todos**):

1. **calendar** — run if ALL of: `(now - last_calendar) >= 7200` AND `7 <= hour <= 22`
2. **todos** — run if: `(now - last_todos) >= 1800`
3. Neither due → reply `HEARTBEAT_OK` immediately, stop here.

Use `0` as the last-run time for any key missing from the state file (treat as never run).

---

### `calendar` check

```
exec("python3 ~/.nanobot/workspace/skills/google-calendar/list-calendar.py")
```

- Parse the JSON output for events starting within the next **3 hours**.
- If any found → send via `message()`: event name, start time, and one-line context (location or weather if relevant).
- If none found → no message.

Then update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['calendar']=int(time.time()); p.write_text(json.dumps(s))\"")
```

---

### `todos` check

```
exec("grep -A 200 '## Todos' ~/.nanobot/workspace/memory/MEMORY.md")
```

- If the output contains any **unchecked** lines (`- [ ] ...`) → send via `message()`: a short bulleted list of open items.
- If no unchecked todos → no message.

Then update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['todos']=int(time.time()); p.write_text(json.dumps(s))\"")
```

---

### Step 3 — Reply

- Sent a `message()` → reply `HEARTBEAT_DONE`
- No message sent → reply `HEARTBEAT_OK`
