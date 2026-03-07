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
2. **whatsapp** — if `(now - last_whatsapp) >= 1800`
3. **todos** — if `(now - last_todos) >= 1800`
4. **reddit** — if `(now - last_reddit) >= 82800` AND `7 <= hour <= 10`
5. No condition met → reply `HEARTBEAT_OK`, stop here.

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

### `whatsapp` check

```
exec("python3 ~/.nanobot/workspace/skills/whatsapp-monitor/query_recent.py")
```

- If output is `NO_NEW_WHATSAPP_MESSAGES` → reply `HEARTBEAT_OK`.
- If output contains messages:
  1. Summarise into a tight digest: 1 line per contact (who sent what, how many messages).
  2. Include the summary in your final reply (it will be delivered to Telegram).
  3. Keep it under 10 lines. Mention the contact's number and the gist only.

Update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['whatsapp']=int(time.time()); p.write_text(json.dumps(s))\"")
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

### `reddit` check

Fetch hot posts from all 5 subreddits simultaneously (one call per subreddit):

```
reddit_search(query="world news", subreddit="worldnews", sort="hot", limit=25)
reddit_search(query="australia", subreddit="australia", sort="hot", limit=20)
reddit_search(query="finance economy", subreddit="ausfinance", sort="hot", limit=15)
reddit_search(query="artificial intelligence", subreddit="MachineLearning", sort="hot", limit=25)
reddit_search(query="LLM model release", subreddit="LocalLLaMA", sort="hot", limit=20)
```

From all results combined:
- Sort each category's posts by score descending.
- Take the top 10 per category. Do NOT filter, summarise, or editorially exclude anything.
- Format each post as a markdown link using the exact permalink from the search result.

Format exactly like this:

```
📰 Reddit — {Day Date}

🌍 Global
• [title](permalink_url)
• [title](permalink_url)
...

🇦🇺 Australia
• [title](permalink_url)
...

🤖 AI
• [title](permalink_url)
...
```

Use the exact post title — do not paraphrase or shorten. Do not add scores, commentary, or any other text.

Update state:
```
exec("python3 -c \"import json,time,pathlib; p=pathlib.Path.home()/'.nanobot/workspace/heartbeat-state.json'; s=json.loads(p.read_text()) if p.exists() else {}; s['reddit']=int(time.time()); p.write_text(json.dumps(s))\"")
```

---

### Step 3 — Record outcome (lightweight)

**Only if the check produced a notification** (not on HEARTBEAT_OK), append one line to `memory/HISTORY.md`:

```
exec("echo '$(date +%Y-%m-%d\\ %H:%M) | heartbeat:<check_name> | <brief outcome>' >> ~/.nanobot/workspace/memory/HISTORY.md")
```

Example: `2026-03-04 14:30 | heartbeat:calendar | notified: Team standup in 45min`

**Skip this step entirely on HEARTBEAT_OK** — do not log empty ticks.

---

### Final reply

- Something to notify → reply with the notification text (no preamble, no questions).
- Nothing actionable → reply `HEARTBEAT_OK`.
