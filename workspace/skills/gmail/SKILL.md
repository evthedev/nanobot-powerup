---
name: gmail
description: Read Gmail emails for the owner — list inbox, search, fetch full message body.
---

# Gmail Skill

Read emails from the owner's Gmail account. Uses the existing `google_calendar` OAuth token (which already includes `gmail.readonly` scope) — no separate auth needed.

## Credentials & Prerequisites

Loaded automatically from `~/.nanobot/config.json` → `tools.google_calendar.tokens`.

**One-time requirement:** The Gmail API must be enabled in the Google Cloud project. Visit:
> https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=815745064634

Click **Enable**, wait ~1 minute, then this skill works with no other changes.

## Usage

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.nanobot/workspace/skills-auto/gmail'))
from gmail_helper import list_emails, search_emails, get_email, get_unread_count
```

### List recent inbox emails
```python
emails = list_emails(max_results=10)
for e in emails:
    print(e['date'], e['from'], e['subject'])
```

### List unread emails only
```python
emails = list_emails(max_results=20, query='is:unread')
```

### Search emails
```python
results = search_emails('from:boss@company.com subject:invoice', max_results=5)
```

### Fetch a full email body
```python
email = get_email('MESSAGE_ID_HERE')
print(email['body'])
```

### Get unread count
```python
count = get_unread_count()  # defaults to INBOX
print(f"You have {count} unread emails")
```

## Return shape

Each email dict has:
- `id` — Gmail message ID
- `thread_id` — thread it belongs to
- `subject` — subject line
- `from` — sender address
- `to` — recipient(s)
- `date` — raw date header string
- `snippet` — short preview (Gmail-generated)
- `body` — full plain-text body (decoded)
- `labels` — list of Gmail label IDs (e.g. `["INBOX", "UNREAD"]`)

## Gmail query syntax (for `query` / `search_emails`)

| Goal | Query string |
|------|-------------|
| Unread only | `is:unread` |
| From a person | `from:name@example.com` |
| Subject keyword | `subject:invoice` |
| Date range | `after:2026/01/01 before:2026/02/01` |
| Has attachment | `has:attachment` |
| Specific label | `label:important` |

## Notes
- Max results per call is 500 (Gmail API limit per page — use multiple calls + pagination for more).
- This skill is read-only (`gmail.readonly` scope); it cannot send, delete, or modify emails.
- To send emails, a `gmail.send` scope would need to be added and re-auth performed.
