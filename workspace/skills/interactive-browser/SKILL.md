# Skill: Interactive Browser (Playwright E2E)

## Purpose
Move beyond static `screenshot_pages` to full browser-based task automation.

## Overlap Merge
- **Existing:** `screenshot_pages` (static capture).
- **New Capability:** Uses Playwright to click, type, and navigate multi-step web forms or authenticated sessions.

## How to execute
Use the `exec` tool to run the consolidated interactive capture script for difficult, slow-loading (hydrating), or bot-protected sites.

```bash
python3 ~/.nanobot/workspace/skills-auto/interactive-browser/interactive_capture.py "<URL>" "<SLUG>" "<LABEL>" [WAIT_TIME]
```

### Parameters:
- `URL`: The full target URL.
- `SLUG`: Hyphenated identifier for the task (e.g., `psw-quote`).
- `LABEL`: Short label for the specific page (e.g., `form-view`).
- `WAIT_TIME`: (Optional) Defaults to **25 seconds**. Use 25+ for complex CRM sites (HubSpot, McKercher, Salesforce).

## Interaction Logic
1. **Stealth Launch:** Spoofs hardware IDs and removes the `webdriver` flag.
2. **Human-Mimicry:** Performs jittery mouse movements and incremental scrolling to wake up "Lazy-Load" observers.
3. **Hydration Wait:** Implements a mandatory 25-second wait to allow slow JavaScript components (like CRM forms) to populate the DOM.
4. **Full-Page Capture:** Captures the entire rendered page to bypass "Lazy-Load" observers that only trigger when a user scrolls.

## Instructions
1. For complex web tasks (e.g., "Fill out this solar form"), use the `interactive_capture.py` script.
2. Use `exec` to run the script in a headless browser.
3. Capture screenshots of the *confirmation page* as proof of action.
4. Handle redirects and dynamic content that `web_fetch` cannot see.
