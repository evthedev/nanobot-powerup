import asyncio
import random
import sys
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def interactive_capture(url, slug, label, wait_time=25):
    """
    Consolidated interactive browser script for capturing difficult, 
    slow-loading (hydrating), or bot-protected sites.
    """
    async with async_playwright() as p:
        # 1. Setup - Persistent context to simulate a real user session
        user_data_dir = Path("/tmp/interactive_browser_context")
        user_data_dir.mkdir(exist_ok=True)
        
        # 2. Launch with high-end hardware spoofing
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            }
        )
        
        page = browser.pages[0] if browser.pages else await browser.new_page()
        
        # 3. Stealth - Remove 'webdriver' flag and spoof basic canvas
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        print(f"[*] Navigating to {url}...")
        try:
            # 4. Navigation - Use domcontentloaded to handle heavy JS sites better
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # 5. Human-Mimicry - Jittery mouse movement and scrolling to trigger observers
            print(f"[*] Mimicking human interaction and waiting {wait_time}s for hydration...")
            for _ in range(3):
                await page.mouse.move(random.randint(200, 800), random.randint(200, 800), steps=10)
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(random.uniform(1.0, 2.0))
            
            # 6. Hydration Check - The core fix for slow CRM-heavy forms (like PSW)
            await asyncio.sleep(wait_time - 6) # Remaining time after mimicry
            
            # 7. Capture - Full page screenshot to bypass lazy-load traps
            screenshot_dir = Path("/root/.nanobot/workspace/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = screenshot_dir / f"{slug}-{label}.png"
            
            await page.screenshot(path=str(path), full_page=True)
            print(f"[+] Success: Screenshot saved to {path}")
            
            # 8. Content Extraction - Return some text for reasoning
            title = await page.title()
            print(f"[+] Page Title: {title}")
            
        except Exception as e:
            print(f"[!] Error during capture: {e}")
            
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 interactive_capture.py <url> <slug> <label> [wait_time]")
        sys.exit(1)
        
    url = sys.argv[1]
    slug = sys.argv[2]
    label = sys.argv[3]
    wait_time = int(sys.argv[4]) if len(sys.argv) > 4 else 25
    
    asyncio.run(interactive_capture(url, slug, label, wait_time))
