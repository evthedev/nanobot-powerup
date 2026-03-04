#!/usr/bin/env python3
"""
Stealth form submission: CloakBrowser (fingerprint evasion) + CapSolver (CAPTCHA solving).

USAGE:
  1. Copy this file:  cp submit_form.py ~/.nanobot/workspace/my_task.py
  2. Edit the CONFIG section below
  3. Run: python3 my_task.py

RULES:
  - Sync API only — never wrap launch() in asyncio.run()
  - Async variant: from cloakbrowser import launch_async  (NOT async_launch)
  - Never use page.wait_for_timeout() — use time.sleep() instead (CDP leak)
"""
import json
import time
import sys
import datetime
from pathlib import Path

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)

# ── CONFIG — edit these before running ───────────────────────────────────────
TARGET_URL      = "https://example.com/contact"
SCREENSHOT_PATH = "/root/.nanobot/workspace/screenshots/submission_result.png"
FINGERPRINT     = "42069"   # fixed seed = consistent returning-visitor fingerprint

# CSS selector → value to type.  Comment out fields that don't exist on the form.
FORM_FIELDS = {
    "input[name='your-name']":    "Your Name",
    "input[type='email']":        "email@example.com",
    "input[type='tel']":          "0400000000",
    "textarea":                   "Message content here.",
}
SUBMIT_SELECTOR = "input[type='submit'], button[type='submit']"
# ─────────────────────────────────────────────────────────────────────────────

log("=== stealth submit_form.py starting ===")
log(f"Target: {TARGET_URL}")

# Load CapSolver key
config = json.loads((Path.home() / ".nanobot/config.json").read_text())
import capsolver
capsolver.api_key = config["tools"]["capsolver"]["api_key"]
log(f"CapSolver key loaded: {capsolver.api_key[:20]}...")

# Verify CapSolver balance before spending time loading the page
try:
    balance = capsolver.balance()
    bal_amount = balance.get("balance", 0) if isinstance(balance, dict) else getattr(balance, "balance", 0)
    log(f"CapSolver balance: ${bal_amount}")
    if float(bal_amount) <= 0:
        log("ABORT: CapSolver balance is zero — top up at dashboard.capsolver.com")
        sys.exit(1)
except Exception as e:
    log(f"WARNING: could not check balance ({e}) — continuing anyway")

# ── Step 1 — Launch CloakBrowser ─────────────────────────────────────────────
log("[1/6] Launching CloakBrowser (sync API)...")
from cloakbrowser import launch
browser = launch(headless=True, args=[f"--fingerprint={FINGERPRINT}"])
page = browser.new_page()
log("      Browser launched OK")

try:
    # ── Step 2 — Navigate ────────────────────────────────────────────────────
    log(f"[2/6] Navigating to {TARGET_URL}...")
    t0 = time.time()
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    log(f"      domcontentloaded in {time.time()-t0:.1f}s")
    log("      Sleeping 5s for Cloudflare interstitial to clear...")
    time.sleep(5)
    log(f"      Page title : {page.title()!r}")
    log(f"      Final URL  : {page.url}")

    # Snapshot all inputs so we can see what the form actually has
    inputs_info = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
            tag: el.tagName, type: el.type || '', name: el.name || '',
            id: el.id || '', placeholder: (el.placeholder || '').substring(0, 40),
            visible: el.offsetParent !== null
        }));
    }""")
    log(f"      Form elements found ({len(inputs_info)}):")
    for el in inputs_info:
        log(f"        <{el['tag'].lower()} type={el['type']!r} name={el['name']!r} id={el['id']!r} placeholder={el['placeholder']!r} visible={el['visible']}>")

    # ── Step 3 — CAPTCHA detection + solving ─────────────────────────────────
    log("[3/6] Detecting CAPTCHA...")

    # reCAPTCHA v2 sitekey (data-sitekey attr or iframe src)
    sitekey = page.evaluate("""() => {
        const el = document.querySelector('[data-sitekey]');
        if (el) return el.getAttribute('data-sitekey');
        const iframe = document.querySelector('iframe[src*="recaptcha"]');
        if (iframe) { const m = iframe.src.match(/[?&]k=([^&]+)/); return m ? m[1] : null; }
        return null;
    }""")

    if sitekey:
        log(f"      reCAPTCHA v2 detected — sitekey: {sitekey}")
        log("      Calling CapSolver (ReCaptchaV2TaskProxyLess)...")
        t0 = time.time()
        solution = capsolver.solve({
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": page.url,
            "websiteKey": sitekey,
        })
        token = solution.get("gRecaptchaResponse") or solution.get("token")
        if not token:
            raise RuntimeError(f"CapSolver returned no token. Full response: {solution}")
        log(f"      Token received in {time.time()-t0:.1f}s: {token[:50]}...")

        page.evaluate(f"""() => {{
            // Set hidden textarea
            const ta = document.getElementById('g-recaptcha-response');
            if (ta) {{ ta.value = '{token}'; ta.style.display = 'block'; }}
            // Fire any registered callback
            try {{
                const cfg = window.___grecaptcha_cfg;
                if (cfg && cfg.clients) {{
                    for (const k in cfg.clients) {{
                        for (const p in cfg.clients[k]) {{
                            const c = cfg.clients[k][p];
                            if (c && typeof c.callback === 'function') c.callback('{token}');
                        }}
                    }}
                }}
            }} catch(e) {{}}
        }}""")
        time.sleep(2)
        log("      reCAPTCHA token injected + callback fired")

    else:
        # Turnstile
        turnstile_key = page.evaluate("""() => {
            const el = document.querySelector('.cf-turnstile, [data-sitekey]');
            return el ? el.getAttribute('data-sitekey') : null;
        }""")
        if turnstile_key:
            log(f"      Cloudflare Turnstile detected — sitekey: {turnstile_key}")
            log("      Calling CapSolver (AntiTurnstileTaskProxyLess)...")
            t0 = time.time()
            solution = capsolver.solve({
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": page.url,
                "websiteKey": turnstile_key,
            })
            token = solution["token"]
            log(f"      Token received in {time.time()-t0:.1f}s: {token[:50]}...")
            page.evaluate(f"""() => {{
                document.querySelectorAll('[name="cf-turnstile-response"]')
                    .forEach(el => el.value = '{token}');
            }}""")
            time.sleep(2)
            log("      Turnstile token injected")
        else:
            log("      No CAPTCHA widget detected — page may have cleared it via CloakBrowser")

    # ── Step 4 — Fill form fields ─────────────────────────────────────────────
    log("[4/6] Filling form fields...")
    filled = 0
    for selector, value in FORM_FIELDS.items():
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.fill(value)
                log(f"      ✓ {selector!r} = {value!r}")
                filled += 1
            else:
                log(f"      ✗ {selector!r} — not found or not visible")
        except Exception as e:
            log(f"      ✗ {selector!r} — ERROR: {e}")
    log(f"      {filled}/{len(FORM_FIELDS)} fields filled")

    # ── Step 5 — Submit ───────────────────────────────────────────────────────
    log("[5/6] Clicking submit...")
    submit = page.query_selector(SUBMIT_SELECTOR)
    if submit and submit.is_visible():
        submit_text = submit.get_attribute("value") or submit.inner_text()
        log(f"      Submit button found: {submit_text!r}")
        submit.click()
        log("      Clicked — waiting 5s for response...")
        time.sleep(5)
    else:
        log("      WARNING: no visible submit button — pressing Enter")
        page.keyboard.press("Enter")
        time.sleep(5)

    # ── Step 6 — Verify + screenshot ─────────────────────────────────────────
    log("[6/6] Verifying result...")
    current_url = page.url
    page_text = page.inner_text("body")
    log(f"      URL after submit: {current_url}")
    log(f"      Page text (first 400 chars): {page_text[:400]!r}")

    SUCCESS_KEYWORDS = ["thank you", "thanks", "success", "submitted", "received", "we'll be in touch", "we will be in touch", "confirmation"]
    matched = [kw for kw in SUCCESS_KEYWORDS if kw in page_text.lower()]
    success = bool(matched)

    Path(SCREENSHOT_PATH).parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=SCREENSHOT_PATH, full_page=True)
    api_url = f"/api/screenshots/{Path(SCREENSHOT_PATH).name}"
    log(f"      Screenshot saved: {SCREENSHOT_PATH}")

    if success:
        log(f"\n✅ SUCCESS — matched keywords: {matched}")
        log(f"   Image URL  : {api_url}")
        log(f"   Embed this : ![Submission result]({api_url})")
    else:
        log(f"\n⚠️  UNCONFIRMED — no success keyword found in page text")
        log(f"   Image URL  : {api_url}")
        log(f"   Check the screenshot to confirm manually")

except Exception as e:
    log(f"\n❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
    # Always capture a failure screenshot for diagnosis
    try:
        fail_path = SCREENSHOT_PATH.replace(".png", "_ERROR.png")
        page.screenshot(path=fail_path, full_page=True)
        log(f"   Error screenshot: {fail_path}")
    except Exception:
        pass
    sys.exit(1)

finally:
    browser.close()
    log("Browser closed.")
    log("=== submit_form.py done ===")
