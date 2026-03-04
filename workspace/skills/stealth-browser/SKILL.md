# Stealth Browser Skill

Use this skill whenever a scraping or automation task hits bot detection, Cloudflare, Turnstile, reCAPTCHA, or any anti-bot system.

## Mandatory Approach — Always Follow This Order

```
1. CloakBrowser  →  loads the page past Cloudflare interstitial
2. CapSolver     →  solves any embedded Turnstile/CAPTCHA widget
3. Fill + submit the form
```

**Never attempt a protected site with standard Playwright. Never rely on CloakBrowser alone for Turnstile — always pair with CapSolver.**

---

## Step 1 — Load Page with CloakBrowser

```python
from cloakbrowser import launch
import time

browser = launch(headless=True, args=["--fingerprint=42069"])  # fixed seed = returning visitor
page = browser.new_page()
page.goto("https://protected-site.com", wait_until="domcontentloaded", timeout=60000)
time.sleep(5)  # allow Cloudflare interstitial to clear
```

> Use `time.sleep()` not `page.wait_for_timeout()` — the latter sends CDP commands that reCAPTCHA detects.

---

## Step 2 — Solve Turnstile with CapSolver (PRIMARY)

Always attempt CapSolver for any Cloudflare-protected page before trying to interact with the form.

```python
import capsolver
import json
from pathlib import Path

# Load API key from config
config = json.loads((Path.home() / ".nanobot/config.json").read_text())
capsolver.api_key = config["tools"]["capsolver"]["api_key"]

# Extract sitekey from page
sitekey = page.evaluate("""() => {
    const el = document.querySelector('[data-sitekey]');
    return el ? el.getAttribute('data-sitekey') : null;
}""")

if sitekey:
    print(f"Solving Turnstile sitekey: {sitekey}")
    solution = capsolver.solve({
        "type": "AntiTurnstileTaskProxyLess",
        "websiteURL": page.url,
        "websiteKey": sitekey,
    })
    token = solution["token"]

    # Inject token into page
    page.evaluate(f"""() => {{
        const inputs = document.querySelectorAll('[name="cf-turnstile-response"]');
        inputs.forEach(el => el.value = '{token}');
    }}""")
    print(f"Turnstile token injected: {token[:40]}...")
    time.sleep(2)
else:
    print("No Turnstile sitekey found — page may have loaded cleanly")
```

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
| CloakBrowser | Browser fingerprint | Cloudflare interstitial, bot score checks |
| CapSolver | Active CAPTCHA solve | Embedded Turnstile, reCAPTCHA widgets |

They solve different problems. Both are required for fully protected forms.

---

## Installation

Both are pre-installed in the Docker image. CloakBrowser binary is pre-downloaded at build time.

```bash
# If running locally:
pip install cloakbrowser capsolver
```
