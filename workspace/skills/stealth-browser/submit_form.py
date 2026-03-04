#!/usr/bin/env python3
"""
Stealth form submission: CloakBrowser (fingerprint evasion) + CapSolver (CAPTCHA solving).
Handles reCAPTCHA v2 checkbox, v2 invisible, and v3 invisible automatically.

USAGE:
  1. Copy:   cp submit_form.py ~/.nanobot/workspace/my_task.py
  2. Edit:   only the CONFIG section below (TARGET_URL, FORM_FIELDS, SCREENSHOT_PATH)
  3. Run:    python3 my_task.py

RULES (do not modify the logic below CONFIG):
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

# ── CONFIG — edit only this section ──────────────────────────────────────────
TARGET_URL      = "https://example.com/contact"
SCREENSHOT_PATH = "/root/.nanobot/workspace/screenshots/submission_result.png"

# CSS selector → value.  Remove selectors that don't exist on this form.
FORM_FIELDS = {
    "input[name='your-name']":    "Your Name",
    "input[type='email']":        "email@domain.com",
    "input[type='tel']":          "0400000000",
    "textarea":                   "Message here.",
}
SUBMIT_SELECTOR = "input[type='submit'], button[type='submit']"

# reCAPTCHA v3 action string — usually "gform", "submit", or "homepage".
# Check the form's JS source if unsure; "gform" is correct for Gravity Forms.
RECAPTCHA_V3_ACTION = "gform"
# ─────────────────────────────────────────────────────────────────────────────

log("=== submit_form.py starting ===")
log(f"Target: {TARGET_URL}")

# Auto-correct screenshot path — always land in the screenshots/ dir so /api/screenshots/ can serve them
_SCREENSHOTS_DIR = Path.home() / ".nanobot/workspace/screenshots"
_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
_stem = Path(SCREENSHOT_PATH).name
if "/screenshots/" not in SCREENSHOT_PATH:
    SCREENSHOT_PATH = str(_SCREENSHOTS_DIR / _stem)
    log(f"[path-fix] SCREENSHOT_PATH corrected to: {SCREENSHOT_PATH}")

# Load CapSolver key + verify balance
config = json.loads((Path.home() / ".nanobot/config.json").read_text())
import capsolver
capsolver.api_key = config["tools"]["capsolver"]["api_key"]
log(f"CapSolver key: {capsolver.api_key[:20]}...")
try:
    bal = capsolver.balance()
    amount = bal.get("balance", 0) if isinstance(bal, dict) else getattr(bal, "balance", 0)
    log(f"CapSolver balance: ${amount}")
    if float(amount) <= 0:
        log("ABORT: CapSolver balance is zero — top up at dashboard.capsolver.com")
        sys.exit(1)
except Exception as e:
    log(f"WARNING: balance check failed ({e}) — continuing")

# Memory-saving flags — required on small EC2 instances (< 4GB RAM)
BROWSER_ARGS = [
    "--fingerprint=42069",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--js-flags=--max-old-space-size=256",
    "--renderer-process-limit=1",
    "--disable-background-networking",
]

# ── Step 1 — Launch CloakBrowser (sync API — never use asyncio.run()) ────────
log("[1/6] Launching CloakBrowser...")
from cloakbrowser import launch
browser = launch(headless=True, args=BROWSER_ARGS)
page = browser.new_page()
log("      OK")

try:
    # ── Step 2 — Navigate + wait for Cloudflare interstitial ─────────────────
    log(f"[2/6] Navigating to {TARGET_URL}...")
    t0 = time.time()
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    log(f"      loaded in {time.time()-t0:.1f}s — sleeping 5s for CF interstitial")
    time.sleep(5)
    log(f"      title : {page.title()!r}")
    log(f"      url   : {page.url}")

    # Enumerate all visible form elements for debugging
    inputs = page.evaluate("""() =>
        Array.from(document.querySelectorAll('input,textarea,select')).map(el => ({
            tag: el.tagName, type: el.type || '', name: el.name || '',
            id: el.id || '', cls: (el.className || '').substring(0, 60),
            visible: el.offsetParent !== null
        }))
    """)
    log(f"      {len(inputs)} form elements discovered:")
    for el in inputs:
        if el["visible"]:
            log(f"        <{el['tag'].lower()} type={el['type']!r} name={el['name']!r} id={el['id']!r}>")

    # ── Step 3 — Detect CAPTCHA type and solve ────────────────────────────────
    log("[3/6] Detecting CAPTCHA...")

    captcha_info = page.evaluate("""() => {
        // Find all [data-sitekey] elements
        const widgets = Array.from(document.querySelectorAll('[data-sitekey]')).map(el => ({
            sitekey: el.getAttribute('data-sitekey'),
            cls: el.className || '',
            size: el.getAttribute('data-size') || '',
            badge: el.getAttribute('data-badge') || '',
            callback: el.getAttribute('data-callback') || '',
        }));

        // Check for v3 via render=<key> in <script src>
        const scripts = Array.from(document.querySelectorAll('script[src]'));
        const v3script = scripts.find(s => s.src.includes('recaptcha/api.js') && s.src.includes('render='));
        const v3sitekey = v3script ? (v3script.src.match(/render=([^&]+)/) || [])[1] : null;

        // Check for invisible via iframe size=invisible
        const iframes = Array.from(document.querySelectorAll('iframe[src*="recaptcha"]'));
        const invisIframe = iframes.find(f => f.src.includes('size=invisible'));

        // Detect form ID (Gravity Forms)
        const forms = Array.from(document.querySelectorAll('form[id^="gform_"]'));
        const formId = forms.length ? forms[0].id.replace('gform_', '') : null;

        return { widgets, v3sitekey, hasInvisibleIframe: !!invisIframe, formId };
    }""")

    log(f"      CAPTCHA info: {captcha_info}")

    sitekey = None
    captcha_type = None  # "v2_checkbox" | "v2_invisible" | "v3"
    token = None

    # Determine type from detection results
    # NOTE: render=explicit means v2 rendered manually — ignore it, fall through to widgets
    _v3key = captcha_info.get("v3sitekey")
    if _v3key and _v3key not in ("explicit", "onload", ""):
        # reCAPTCHA v3 (render=<real_sitekey> in api.js)
        sitekey = _v3key
        captcha_type = "v3"
    elif captcha_info.get("widgets"):
        w = captcha_info["widgets"][0]
        sitekey = w["sitekey"]
        if "v3" in w["cls"].lower() or "invisible" in w["cls"].lower() or captcha_info.get("hasInvisibleIframe"):
            captcha_type = "v2_invisible"
        else:
            captcha_type = "v2_checkbox"
    else:
        log("      No CAPTCHA detected — page may have cleared naturally via CloakBrowser")

    if sitekey:
        log(f"      Type    : {captcha_type}")
        log(f"      Sitekey : {sitekey}")

        if captcha_type == "v3":
            log(f"      Solving reCAPTCHA v3 via CapSolver (action={RECAPTCHA_V3_ACTION!r})...")
            t0 = time.time()
            sol = capsolver.solve({
                "type": "ReCaptchaV3TaskProxyLess",
                "websiteURL": page.url,
                "websiteKey": sitekey,
                "pageAction": RECAPTCHA_V3_ACTION,
                "minScore": 0.5,
            })
            token = sol.get("gRecaptchaResponse") or sol.get("token")
            log(f"      Token in {time.time()-t0:.1f}s: {(token or '')[:60]}...")

            if token:
                form_id = captcha_info.get("formId")
                log(f"      Gravity Forms form_id: {form_id!r}")
                page.evaluate(f"""() => {{
                    const tok = '{token}';
                    // Gravity Forms v3: store in gform.recaptchaTokens
                    try {{
                        if (window.gform && window.gform.recaptchaTokens) {{
                            window.gform.recaptchaTokens['{form_id}'] = tok;
                            console.log('[CapSolver] set gform.recaptchaTokens[{form_id}]');
                        }}
                    }} catch(e) {{ console.log('[CapSolver] gform.recaptchaTokens error:', e); }}
                    // Also inject into any hidden recaptcha fields
                    document.querySelectorAll('[name*="recaptcha"],[name*="g-recaptcha"]').forEach(el => {{
                        el.value = tok;
                        console.log('[CapSolver] set hidden field:', el.name);
                    }});
                    // Fire any grecaptcha callbacks registered via execute()
                    try {{
                        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {{
                            for (const k in window.___grecaptcha_cfg.clients) {{
                                for (const p in window.___grecaptcha_cfg.clients[k]) {{
                                    const c = window.___grecaptcha_cfg.clients[k][p];
                                    if (c && typeof c.callback === 'function') c.callback(tok);
                                }}
                            }}
                        }}
                    }} catch(e) {{}}
                }}""")
                time.sleep(2)
                log("      v3 token injected into gform.recaptchaTokens + hidden fields")
            else:
                raise RuntimeError(f"CapSolver returned no token. Response: {sol}")

        elif captcha_type in ("v2_invisible", "v2_checkbox"):
            task_type = "ReCaptchaV2TaskProxyLess"
            log(f"      Solving {captcha_type} via CapSolver ({task_type})...")
            t0 = time.time()
            payload = {
                "type": task_type,
                "websiteURL": page.url,
                "websiteKey": sitekey,
            }
            if captcha_type == "v2_invisible":
                payload["isInvisible"] = True
            sol = capsolver.solve(payload)
            token = sol.get("gRecaptchaResponse") or sol.get("token")
            log(f"      Token in {time.time()-t0:.1f}s: {(token or '')[:60]}...")

            if token:
                # Do NOT set display:block — that makes the textarea cover the submit button
                page.evaluate(f"""() => {{
                    const tok = '{token}';
                    const ta = document.getElementById('g-recaptcha-response');
                    if (ta) {{ ta.value = tok; }}
                    // Fire any registered callback
                    try {{
                        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {{
                            for (const k in window.___grecaptcha_cfg.clients) {{
                                for (const p in window.___grecaptcha_cfg.clients[k]) {{
                                    const c = window.___grecaptcha_cfg.clients[k][p];
                                    if (c && typeof c.callback === 'function') c.callback(tok);
                                }}
                            }}
                        }}
                    }} catch(e) {{}}
                }}""")
                time.sleep(2)
                log("      v2 token injected + callback fired")
            else:
                raise RuntimeError(f"CapSolver returned no token. Response: {sol}")

    # ── Step 4 — Fill form fields ─────────────────────────────────────────────
    log("[4/6] Filling form fields...")
    filled = 0
    for selector, value in FORM_FIELDS.items():
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.fill(value)
                log(f"      + {selector!r} = {value!r}")
                filled += 1
            else:
                log(f"      - {selector!r}: not found or not visible")
        except Exception as e:
            log(f"      - {selector!r}: ERROR {e}")
    log(f"      {filled}/{len(FORM_FIELDS)} fields filled")

    # Screenshot BEFORE submit — proof of fill regardless of what happens next
    Path(SCREENSHOT_PATH).parent.mkdir(parents=True, exist_ok=True)
    prefill = SCREENSHOT_PATH.replace(".png", "_prefilled.png")
    page.screenshot(path=prefill, full_page=True)
    log(f"      Pre-submit screenshot: {prefill}")
    log(f"      Embed prefill: ![Filled form](/api/screenshots/{Path(prefill).name})")

    # ── Step 5 — Submit via JS click (bypasses pointer-event interception) ────
    log("[5/6] Submitting...")
    sel_escaped = SUBMIT_SELECTOR.replace("'", "\\'")
    submitted = page.evaluate(f"""() => {{
        const btn = document.querySelector('{sel_escaped}');
        if (btn) {{ btn.click(); return btn.id || btn.value || btn.textContent.trim() || 'clicked'; }}
        return null;
    }}""")
    if submitted:
        log(f"      JS click on: {submitted!r}")
    else:
        log("      WARNING: no submit button found — pressing Enter")
        page.keyboard.press("Enter")
    log("      Waiting 6s for response...")
    time.sleep(6)

    # ── Step 6 — Verify + screenshot ─────────────────────────────────────────
    log("[6/6] Verifying result...")
    final_url = page.url
    body_text = page.inner_text("body")
    log(f"      Final URL : {final_url}")
    log(f"      Body (500): {body_text[:500]!r}")

    SUCCESS_KEYWORDS = [
        "thank you", "thanks", "success", "submitted", "received",
        "we'll be in touch", "we will be in touch", "confirmation", "has been sent",
        "enquiry", "get back to you",
    ]
    matched = [kw for kw in SUCCESS_KEYWORDS if kw in body_text.lower()]

    page.screenshot(path=SCREENSHOT_PATH, full_page=True)
    api_url = f"/api/screenshots/{Path(SCREENSHOT_PATH).name}"
    log(f"      Final screenshot : {SCREENSHOT_PATH}")

    if matched:
        log(f"\n✅ SUCCESS — keywords matched: {matched}")
        log(f"   Image URL : {api_url}")
        log(f"   Embed     : ![Result]({api_url})")
    else:
        log(f"\n⚠️  UNCONFIRMED — no success keyword in page text")
        log(f"   Image URL : {api_url}")
        log(f"   Check screenshot for errors")
        # Print validation errors if any
        errors = page.evaluate("""() => {
            const errs = document.querySelectorAll('.gfield_error,.validation_error,.error,[class*="error"],[class*="Error"]');
            return Array.from(errs).map(e => e.textContent.trim().substring(0,120)).filter(Boolean);
        }""")
        if errors:
            log(f"   Validation errors: {errors}")

except Exception as e:
    log(f"\n❌ FATAL: {e}")
    import traceback
    traceback.print_exc()
    try:
        Path(SCREENSHOT_PATH).parent.mkdir(parents=True, exist_ok=True)
        err_path = SCREENSHOT_PATH.replace(".png", "_ERROR.png")
        page.screenshot(path=err_path, full_page=True)
        log(f"   Error screenshot: {err_path}")
        log(f"   Embed: ![Error](/api/screenshots/{Path(err_path).name})")
    except Exception:
        pass
    sys.exit(1)

finally:
    browser.close()
    log("Browser closed.")
    log("=== submit_form.py done ===")
