#!/usr/bin/env python3
"""
Send email via Gmail (SMTP + App Password).
Uses only stdlib — no extra packages required.

USAGE:
  1. Copy:   cp send_email.py ~/.nanobot/workspace/my_email.py
  2. Edit:   only the CONFIG section below
  3. Run:    python3 ~/.nanobot/workspace/my_email.py

SETUP (one-time):
  - Enable 2FA on the Gmail account
  - Generate an App Password: myaccount.google.com/apppasswords
  - Store credentials in ~/.nanobot/config.json (see SKILL.md)
"""
import json
import os
import smtplib
import sys
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


# ── CONFIG — edit only this section ──────────────────────────────────────────
TO          = ["recipient@example.com"]   # list of To addresses
CC          = []                          # list of CC addresses (empty = no CC)
SUBJECT     = "Subject here"
BODY_HTML   = """
<p>Hello,</p>
<p>Message body here. Supports <strong>HTML</strong>.</p>
<p>Regards,<br>nanobot</p>
"""
ATTACHMENTS = []   # list of absolute file paths, e.g. ["/tmp/report.pdf"]
# ─────────────────────────────────────────────────────────────────────────────

log("=== send_email.py starting ===")
log(f"To: {TO}")
log(f"Subject: {SUBJECT!r}")

# Load credentials — env vars take priority, then config.json
SENDER       = os.environ.get("GMAIL_EMAIL", "")
APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

if not SENDER or not APP_PASSWORD:
    config_path = Path.home() / ".nanobot/config.json"
    try:
        config = json.loads(config_path.read_text())
        gmail_cfg = config["tools"]["gmail"]
        SENDER       = SENDER       or gmail_cfg.get("email", "")
        APP_PASSWORD = APP_PASSWORD or gmail_cfg.get("app_password", "")
    except (KeyError, FileNotFoundError) as e:
        log(f"❌ Config error: {e}")
        log("   Set env vars GMAIL_EMAIL + GMAIL_APP_PASSWORD, or add to ~/.nanobot/config.json:")
        log('   {"tools": {"gmail": {"email": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"}}}')
        sys.exit(1)

if not SENDER or not APP_PASSWORD:
    log("❌ Gmail credentials missing — set GMAIL_EMAIL + GMAIL_APP_PASSWORD env vars or config.json")
    sys.exit(1)

log(f"Sender: {SENDER}")

# Build message
msg = MIMEMultipart("alternative")
msg["From"]    = SENDER
msg["To"]      = ", ".join(TO)
msg["Subject"] = SUBJECT
if CC:
    msg["Cc"] = ", ".join(CC)

# Attach plain-text fallback + HTML body
plain = BODY_HTML.replace("<br>", "\n").replace("</p>", "\n\n")
import re
plain = re.sub(r"<[^>]+>", "", plain).strip()
msg.attach(MIMEText(plain, "plain"))
msg.attach(MIMEText(BODY_HTML, "html"))

# Attach files if any
for file_path in ATTACHMENTS:
    p = Path(file_path)
    if not p.exists():
        log(f"⚠️  Attachment not found, skipping: {file_path}")
        continue
    part = MIMEBase("application", "octet-stream")
    part.set_payload(p.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{p.name}"')
    msg.attach(part)
    log(f"   + Attachment: {p.name} ({p.stat().st_size // 1024}KB)")

# Send
all_recipients = TO + CC
log(f"Connecting to smtp.gmail.com:587...")
try:
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SENDER, APP_PASSWORD)
        smtp.sendmail(SENDER, all_recipients, msg.as_string())
    log(f"✅ Sent to: {all_recipients}")
    log("=== send_email.py done ===")
except smtplib.SMTPAuthenticationError:
    log("❌ Auth failed — check app_password in config.json")
    log("   App passwords: myaccount.google.com/apppasswords")
    sys.exit(1)
except Exception as e:
    log(f"❌ SMTP error: {e}")
    sys.exit(1)
