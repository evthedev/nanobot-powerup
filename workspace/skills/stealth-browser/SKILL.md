# Stealth Browser Skill

Use this skill whenever a scraping or automation task hits bot detection, Cloudflare, Turnstile, reCAPTCHA, or any anti-bot system.

## Mandatory Approach — Always Follow This Order

```
1. Patchright  →  loads the page past Cloudflare interstitial (pre-installed via scrapling[all])
2. CapSolver   →  solves any embedded Turnstile/CAPTCHA widget
3. Fill + submit the form
```

**Never attempt a protected site with standard Playwright. Never rely on Patchright alone for Turnstile — always pair with CapSolver.**

---

## Ready-to-Run Script — Start Here

**Do NOT write a new script from scratch.** Copy the working script from this skill:

```bash
cp ~/.nanobot/workspace/skills/stealth-browser/submit_form.py ~/.nanobot/workspace/my_task.py
# Edit the CONFIG section at the top, then run:
python3 ~/.nanobot/workspace/my_task.py
```

## Critical API Rules

- **Sync only** — use `patchright.sync_api.sync_playwright` (same Playwright sync interface)
- **No `page.wait_for_timeout()`** — use `import time; time.sleep(N)` (CDP leak vector)

## Screenshot Path — CRITICAL RULE

**ALL screenshots MUST be saved inside `/root/.nanobot/workspace/screenshots/`.**
The `/api/screenshots/` endpoint only serves from that subdirectory — any other path = broken image.

When editing the `SCREENSHOT_PATH` in the CONFIG section, always keep the `screenshots/` directory:
```python
# ✅ CORRECT
SCREENSHOT_PATH = "/root/.nanobot/workspace/screenshots/koala_solar.png"

# ❌ WRONG — image will be broken in the UI
SCREENSHOT_PATH = "/root/.nanobot/workspace/koala_solar.png"
```

Reference in messages as markdown:
```python
# In the message tool:
message(content="Done! ![Result](/api/screenshots/koala_solar.png)")
```

---

## Step 1 — Load Page with Patchright

```python
from patchright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page()
    page.goto("https://protected-site.com", wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)  # allow Cloudflare interstitial to clear
```

> Use `time.sleep()` not `page.wait_for_timeout()` — the latter sends CDP commands that reCAPTCHA detects.

---

## Step 2 — Detect CAPTCHA Type, Then Solve with CapSolver

There are four CAPTCHA types in the wild. Use the correct CapSolver task for each:

| What you see on the page | CapSolver task type | Response key |
|---|---|---|
| `<div class="g-recaptcha" data-sitekey=...>` (checkbox) | `ReCaptchaV2TaskProxyLess` | `gRecaptchaResponse` |
| `<div class="gf_invisible ginput_recaptchav3">` or `api.js?render=key` | `ReCaptchaV3TaskProxyLess` + `pageAction: "gform"` | `gRecaptchaResponse` |
| `size=invisible` in reCAPTCHA iframe | `ReCaptchaV2TaskProxyLess` + `isInvisible: True` | `gRecaptchaResponse` |
| `<div class="cf-turnstile">` | `AntiTurnstileTaskProxyLess` | `token` |

**Do not guess.** Check the page source first:
```python
# Run this to detect type before solving
info = page.evaluate("""() => ({
    v3script: !!(document.querySelector('script[src*="recaptcha/api.js"][src*="render="]')),
    widgets: Array.from(document.querySelectorAll('[data-sitekey]')).map(el => ({
        cls: el.className, sitekey: el.getAttribute('data-sitekey'),
        size: el.getAttribute('data-size')
    })),
    turnstile: !!document.querySelector('.cf-turnstile'),
})""")
print(info)
# v3script=True → ReCaptchaV3TaskProxyLess
# cls contains "invisible" or "v3" → ReCaptchaV2TaskProxyLess + isInvisible=True
# standard checkbox → ReCaptchaV2TaskProxyLess
# turnstile=True → AntiTurnstileTaskProxyLess
```

**IMPORTANT — token injection rules:**
- **Never** set `ta.style.display = 'block'` — making the hidden textarea visible will cover the submit button and block all clicks
- Use JS `btn.click()` not Playwright `.click()` for the submit button (avoids pointer-event interception)
- For reCAPTCHA v3 on Gravity Forms: token goes into `gform.recaptchaTokens[formId]`, not into a textarea

---

## Step 3 — Verify + Fill Form

```python
# Confirm we're past the wall
try:
    page.wait_for_selector("input, textarea, form", timeout=10000)
    print("Form accessible — filling fields")
except:
    print("Form still not accessible after CapSolver — check screenshot")
    page.screenshot(path="/tmp/debug_blocked.png")
    raise

# Fill and submit
page.fill("input[name='your-name']", "Your Name")
page.fill("input[name='your-email']", "email@example.com")
page.fill("textarea[name='your-message']", "Message content")
page.click("input[type='submit'], button[type='submit']")
time.sleep(3)
page.screenshot(path="/tmp/submission_result.png")
```

---

## Config — CapSolver API Key

Store in `~/.nanobot/config.json`:
```json
{
  "tools": {
    "capsolver": {
      "api_key": "YOUR_CAPSOLVER_API_KEY"
    }
  }
}
```

---

## CapSolver Pricing

| CAPTCHA type | Cost |
|---|---|
| Cloudflare Turnstile | $1.20 / 1,000 solves |
| reCAPTCHA v2 | $0.80 / 1,000 solves |
| reCAPTCHA v3 | $1.00 / 1,000 solves |

---

## Comparison

| Tool | Role | Handles |
|---|---|---|
| Patchright | Browser fingerprint | Cloudflare interstitial, bot score checks |
| CapSolver | Active CAPTCHA solve | Embedded Turnstile, reCAPTCHA widgets |

They solve different problems. Both are required for fully protected forms.

---

## Installation

Patchright Python package is pre-installed in the Docker image as part of `scrapling[all]`.
The Chromium binary is downloaded on first use (stored in the persisted `/root/.nanobot/.patchright` volume — no re-download after restarts). The `submit_form.py` template handles this automatically.

```bash
# If running locally:
pip install "scrapling[all]" capsolver
scrapling install  # downloads patchright Chromium
```
