# Gmail Skill

Send emails from the configured Gmail account. No extra packages needed — uses Python stdlib `smtplib`.

---

## ⚠️ MANDATORY: Always Get Explicit Approval Before Sending

**NEVER send an email without the user's explicit approval.** This rule has no exceptions — even if the user previously asked you to send an email, you MUST pause and confirm before executing the send.

Before running any send script, you MUST:

1. Show the user a full preview of the email:
   - **To:** (recipient addresses)
   - **CC:** (if any)
   - **Subject:**
   - **Body:** (full content)
   - **Attachments:** (if any)
2. Ask explicitly: *"Shall I send this email? Please confirm yes or no."*
3. Wait for the user's response.
4. Only proceed if the user says yes (or clear equivalent). If they say no or don't respond clearly, do NOT send.

This approval step is non-negotiable and must happen every single time, regardless of prior instructions in the conversation.

---

## Ready-to-Run Script — Start Here

**Do NOT write a new email script from scratch.** Copy the working script:

```bash
cp ~/.nanobot/workspace/skills/gmail/send_email.py ~/.nanobot/workspace/my_email.py
# Edit the CONFIG section, then run:
python3 ~/.nanobot/workspace/my_email.py
```

Edit **only** the CONFIG section at the top:

```python
TO          = ["recipient@example.com"]   # one or more addresses
CC          = []                          # empty = no CC
SUBJECT     = "Subject here"
BODY_HTML   = "<p>Hello,</p><p>Your message here.</p>"
ATTACHMENTS = []                          # absolute paths, e.g. ["/tmp/report.pdf"]
```

---

## One-Time Setup

1. Enable **2-Step Verification** on the Gmail account:
   `myaccount.google.com/security`

2. Generate an **App Password** (16-character code):
   `myaccount.google.com/apppasswords` → select "Mail" + "Other (nanobot)"

3. Credentials are injected automatically on deploy from GitHub secrets `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` into `~/.nanobot/config.json`. For local use, add them manually:

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

Alternatively, set environment variables directly (takes priority over config.json):
```bash
export GMAIL_EMAIL="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
```

---

## Screenshot Path Rule (if attaching screenshots)

Always reference screenshots from `/root/.nanobot/workspace/screenshots/` so they're accessible via `/api/screenshots/`.

---

## Examples

**Plain notification:**
```python
TO       = ["ev@example.com"]
SUBJECT  = "Nanobot: task complete"
BODY_HTML = "<p>Your task has finished.</p>"
```

**With HTML table:**
```python
BODY_HTML = """
<p>Here is your summary:</p>
<table border="1" cellpadding="6">
  <tr><th>Item</th><th>Value</th></tr>
  <tr><td>Status</td><td>✅ Done</td></tr>
</table>
"""
```

**With attachment:**
```python
ATTACHMENTS = ["/root/.nanobot/workspace/screenshots/result.png"]
```

**Multiple recipients:**
```python
TO = ["alice@example.com", "bob@example.com"]
CC = ["manager@example.com"]
```

---

## Pricing

Free — uses your existing Gmail account via SMTP. App Passwords are free.
Gmail free tier: 500 emails/day. Google Workspace: 2,000/day.
