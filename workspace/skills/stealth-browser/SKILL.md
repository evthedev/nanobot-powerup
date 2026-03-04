# Stealth Browser Skill

Use this skill whenever a scraping or automation task is blocked by bot detection, Cloudflare, reCAPTCHA, FingerprintJS, or any anti-bot system.

## Stack

| Tool | Purpose | Cost |
|------|---------|------|
| **CloakBrowser** | Fingerprint evasion — patches Chromium at C++ source level | Free / open-source |
| **CapSolver** | CAPTCHA solving — Cloudflare Turnstile, reCAPTCHA v2/v3 | ~$1–1.20 per 1,000 solves |

## When to use CloakBrowser

Replace standard Playwright with CloakBrowser for **any site that:**
- Returns a Cloudflare challenge or CAPTCHA on standard Playwright
- Uses FingerprintJS or BrowserScan bot detection
- Checks `navigator.webdriver`, TLS fingerprint, or CDP signals

CloakBrowser passes 30/30 detection tests (verified Mar 2026, Chromium 145). It patches Chromium source code — not JS injection or config flags, which break on every Chrome update.

## Installation

```bash
pip install cloakbrowser
```

On first run, a ~200MB patched Chromium binary is auto-downloaded and cached at `~/.cloakbrowser/`.

## Usage

```python
from cloakbrowser import launch

# Basic (headless by default)
browser = launch()
page = browser.new_page()
page.goto("https://protected-site.com")
browser.close()

# Headed mode — required for some aggressive detectors (DataDome, some Turnstile configs)
browser = launch(headless=False)

# With proxy
browser = launch(proxy="http://user:pass@proxy:8080")

# Persistent fingerprint seed (use same seed per site to appear as returning visitor)
browser = launch(args=["--fingerprint=42069"])

# Async
from cloakbrowser import launch_async
browser = await launch_async()
```

All standard Playwright methods work unchanged — `new_page()`, `new_context()`, `close()`, etc.

> **Tip:** Avoid `page.wait_for_timeout()` — it sends CDP commands that reCAPTCHA detects.
> Use `import time; time.sleep(3)` instead.

## Cloudflare Turnstile via CapSolver

When a Turnstile interactive challenge still appears (even with CloakBrowser):

1. Extract the sitekey from the page DOM:
```python
sitekey = page.locator('[data-sitekey]').get_attribute('data-sitekey')
```

2. Call CapSolver API:
```python
import capsolver  # pip install capsolver

# Load API key from config
import json
from pathlib import Path
config = json.loads((Path.home() / ".nanobot/config.json").read_text())
capsolver.api_key = config["tools"]["capsolver"]["api_key"]

solution = capsolver.solve({
    "type": "AntiTurnstileTaskProxyLess",
    "websiteURL": page.url,
    "websiteKey": sitekey,
})
token = solution["token"]
```

3. Inject the token:
```python
page.evaluate(f"document.querySelector('[name=cf-turnstile-response]').value = '{token}'")
```

4. Verify clearance:
```python
cookies = {c["name"]: c["value"] for c in page.context.cookies()}
assert "cf_clearance" in cookies, "Cloudflare clearance not obtained"
```

## Comparison vs Alternatives

| Tool | Patch level | Playwright API | Turnstile | Status |
|------|------------|----------------|-----------|--------|
| Standard Playwright | None | Native | FAIL | Active |
| playwright-stealth | JS injection | Native | Sometimes | Stale |
| undetected-chromedriver | Config flags | No (Selenium) | Sometimes | Stale |
| Camoufox | C++ (Firefox) | No | Pass | Unstable beta (2026) |
| **CloakBrowser** | **C++ (Chromium)** | **Native** | **Pass** | **Active** |

## Config Key (CapSolver)

Store the CapSolver API key in `~/.nanobot/config.json`:
```json
{
  "tools": {
    "capsolver": {
      "api_key": "YOUR_CAPSOLVER_API_KEY"
    }
  }
}
```
