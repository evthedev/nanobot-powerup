#!/usr/bin/env python3
"""
Stealth form submission: CloakBrowser (fingerprint) + CapSolver (CAPTCHA).
Copy this script, replace the CONFIG section, and run.

Usage:
    python3 submit_form.py
"""
import json
import time
import sys
from pathlib import Path

# ── CONFIG — replace these ────────────────────────────────────────────────────
TARGET_URL   = "https://example.com/contact"
SCREENSHOT   = "/root/.nanobot/workspace/screenshots/submission_result.png"
FINGERPRINT  = "42069"   # fixed seed = consistent identity across sessions

FORM_FIELDS  = {
    # CSS selector → value. Add/remove as needed.
    "input[name='your-name']":    "Your Name",
    "input[type='email']":        "email@example.com",
    "input[type='tel']":          "0400000000",
    "textarea":                   "Message content here.",
}
SUBMIT_SELECTOR = "input[type='submit'], button[type='submit']"
# ─────────────────────────────────────────────────────────────────────────────

# Load CapSolver key from config
config = json.loads((Path.home() / ".nanobot/config.json").read_text())
import capsolver
capsolver.api_key = config["tools"]["capsolver"]["api_key"]

# Step 1 — Launch CloakBrowser (sync API — never use asyncio with this)
print("[1] Launching CloakBrowser...")
from cloakbrowser import launch
browser = launch(headless=True, args=[f"--fingerprint={FINGERPRINT}"])
page = browser.new_page()

try:
    # Step 2 — Load page, allow Cloudflare interstitial to clear
    print(f"[2] Navigating to {TARGET_URL}...")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)  # DO NOT use page.wait_for_timeout() — it leaks CDP signals
    print(f"    Title: {page.title()}")

    # Step 3 — Solve CAPTCHA with CapSolver (always attempt before filling form)
    sitekey = page.evaluate("""() => {
        const el = document.querySelector('[data-sitekey]');
        if (el) return el.getAttribute('data-sitekey');
        const iframe = document.querySelector('iframe[src*="recaptcha"]');
        if (iframe) { const m = iframe.src.match(/[?&]k=([^&]+)/); return m ? m[1] : null; }
        return null;
    }""")

    if sitekey:
        print(f"[3] Solving CAPTCHA (sitekey: {sitekey[:20]}...)...")
        solution = capsolver.solve({
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": page.url,
            "websiteKey": sitekey,
        })
        token = solution.get("gRecaptchaResponse") or solution.get("token")
        if not token:
            raise RuntimeError(f"CapSolver returned no token: {solution}")
        print(f"    Token: {token[:40]}...")

        # Inject token
        page.evaluate(f"""() => {{
            const ta = document.getElementById('g-recaptcha-response');
            if (ta) {{ ta.value = '{token}'; ta.style.display = 'block'; }}
            // Fire callback if registered
            try {{
                const cfg = window.___grecaptcha_cfg;
                if (cfg && cfg.clients) {{
                    for (const k in cfg.clients) {{
                        for (const p in cfg.clients[k]) {{
                            if (cfg.clients[k][p] && cfg.clients[k][p].callback) {{
                                cfg.clients[k][p].callback('{token}');
                            }}
                        }}
                    }}
                }}
            }} catch(e) {{}}
        }}""")
        time.sleep(2)
        print("    Token injected.")
    else:
        print("[3] No CAPTCHA sitekey found — page loaded cleanly or uses Turnstile.")

        # Check for Turnstile
        turnstile_key = page.evaluate("""() => {
            const el = document.querySelector('.cf-turnstile, [data-sitekey]');
            return el ? el.getAttribute('data-sitekey') : null;
        }""")
        if turnstile_key:
            print(f"    Solving Turnstile (sitekey: {turnstile_key[:20]}...)...")
            solution = capsolver.solve({
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": page.url,
                "websiteKey": turnstile_key,
            })
            token = solution["token"]
            page.evaluate(f"""() => {{
                document.querySelectorAll('[name="cf-turnstile-response"]')
                    .forEach(el => el.value = '{token}');
            }}""")
            time.sleep(2)
            print("    Turnstile token injected.")

    # Step 4 — Fill form fields
    print("[4] Filling form...")
    for selector, value in FORM_FIELDS.items():
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.fill(value)
                print(f"    {selector}: {value[:40]}")
        except Exception as e:
            print(f"    WARNING: could not fill {selector}: {e}")

    # Step 5 — Submit
    print("[5] Submitting...")
    submit = page.query_selector(SUBMIT_SELECTOR)
    if submit and submit.is_visible():
        submit.click()
    else:
        print("    WARNING: submit button not found, pressing Enter")
        page.keyboard.press("Enter")
    time.sleep(5)

    # Step 6 — Verify + screenshot
    body = page.inner_text("body").lower()
    success = any(kw in body for kw in ["thank you", "thanks", "success", "submitted", "received", "we'll be in touch"])

    # Save to screenshots/ so it's accessible via /api/screenshots/
    Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=SCREENSHOT)
    slug = Path(SCREENSHOT).stem
    image_url = f"/api/screenshots/{Path(SCREENSHOT).name}"

    if success:
        print(f"\n✅ SUCCESS — form submitted!")
        print(f"   Screenshot: {image_url}")
        print(f"   Embed in message: ![Submission result]({image_url})")
    else:
        print(f"\n⚠️  Submission result unclear. Screenshot: {image_url}")
        print(f"   Page content snippet: {body[:300]}")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)
finally:
    browser.close()
    print("\nBrowser closed.")
