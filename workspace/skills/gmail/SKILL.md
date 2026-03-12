# Gmail Skill

Read emails and send replies from the configured Gmail account.

---

## ⛔ ABSOLUTE RULES — No Exceptions

1. **NEVER fabricate email content.** If you haven't run `read_gmail.py` yet, you do not know what emails exist. Do not guess, infer, or summarise from memory.
2. **NEVER send without explicit user approval.** Show the full draft (To, Subject, Body, Attachments) and wait for a clear "yes" before running `send_email.py`.
3. **NEVER attach an image unless the user explicitly provided its path in this conversation.** Use the EXACT path the user gave — do not invent filenames or guess from context.
4. **NEVER claim an email was sent unless `send_email.py` printed `✅ Sent to:`.**

---

## Step 1 — Always Read First

Before drafting any reply, run `read_gmail.py` to get the real email content.

```bash
# Search by sender name, keyword, or subject
python3 ~/.nanobot/workspace/skills/gmail/read_gmail.py search "PSW" --max 10

# Search all folders (inbox + spam + trash + sent)
python3 ~/.nanobot/workspace/skills/gmail/read_gmail.py search "in:all PSW" --max 10

# List latest inbox emails
python3 ~/.nanobot/workspace/skills/gmail/read_gmail.py list --max 20

# Read a specific email by ID (from search results)
python3 ~/.nanobot/workspace/skills/gmail/read_gmail.py read <message_id>
```

**Gmail query syntax examples:**
- `from:energy-team@pswenergy.com.au` — exact sender
- `subject:solar quote` — subject keyword
- `in:all PSW` — all folders including spam/trash
- `after:2025/01/01 solar` — date-filtered
- `is:unread` — unread only

**After running, show the user:**
- Exact From address
- Exact Subject line
- Exact Date
- Full body (verbatim, not paraphrased)

Only then draft a reply.

---

## Step 2 — Draft the Reply

Write the reply based on the **actual email content** you just read. Do not add information the email didn't contain.

Show the user:
```
To: <exact address from the email>
Subject: Re: <exact subject from the email>
Body:
<full draft>
Attachments: <list exact paths, or "none">
```

Ask: **"Shall I send this? Please confirm yes or no."**

---

## Step 3 — Attaching Images

If the user provided an image path in this conversation (e.g. `/root/.nanobot/media/AgACAgUAAxkBAAIF.jpg`), use that **exact path** in `ATTACHMENTS`.

**Never:**
- Guess a filename from context
- Use a screenshot path unless the user explicitly said to attach a screenshot
- Attach more images than the user specified

---

## Step 4 — Send (only after approval)

Copy `send_email.py`, edit the CONFIG section, run it:

```bash
cp ~/.nanobot/workspace/skills/gmail/send_email.py ~/.nanobot/workspace/my_email.py
# Edit TO, SUBJECT, BODY_HTML, ATTACHMENTS in the CONFIG section
python3 ~/.nanobot/workspace/my_email.py
```

Confirm success by checking the output for `✅ Sent to:`. Report the exact output line to the user.

---

## OAuth Scope Requirement

`read_gmail.py` requires the Gmail API scope. The existing Google OAuth tokens (used for Calendar) must include:
```
https://www.googleapis.com/auth/gmail.readonly
```

If `read_gmail.py` prints `❌ Gmail scope not granted`, the user needs to re-authenticate:
1. Dashboard → Settings → Google Auth
2. The auth flow must request both Calendar and Gmail scopes

To add Gmail scope to the dashboard auth flow, update `dashboard/server/index.js`:
```js
const SCOPES = [
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/gmail.send',   // needed for send via API (optional)
];
```

---

## Credentials (for send_email.py)

`send_email.py` uses SMTP + App Password (separate from OAuth). Credentials in `~/.nanobot/config.json`:

```json
{
  "tools": {
    "gmail": {
      "email": "you@gmail.com",
      "app_password": "xxxx xxxx xxxx xxxx"
    }
  }
}
```

Generate an App Password at: `myaccount.google.com/apppasswords`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `❌ Gmail scope not granted` | Re-auth via dashboard with Gmail scope added |
| `❌ Auth failed` in send | Check `app_password` in config.json — must be App Password, not account password |
| Email not found in inbox | Try `in:all <keyword>` to search all folders including spam/trash |
| `Attachment not found` | Verify the exact file path exists on disk before sending |
