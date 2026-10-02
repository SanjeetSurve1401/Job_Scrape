import os
import time
import sys
import shutil
import json
from dotenv import load_dotenv

load_dotenv()

def update_env_file(key, value, filepath=".env"):
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

STEALTH_JS = """
// Overwrite the 'webdriver' property to prevent bot detection
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Mock chrome runtime
if (!window.chrome) {
    window.chrome = {};
}
window.chrome.runtime = {
    connect: function() {},
    sendMessage: function() {}
};

// Mock plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Mock languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""

DEFAULT_MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

def run_playwright_login():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[INFO] Playwright is not installed. Installing playwright and chromium/chrome...")
        import subprocess
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            from playwright.sync_api import sync_playwright
        except Exception as e:
            print(f"[ERROR] Playwright install failed: {e}")
            return None

    print("\nOpening Stealth Browser for Glassdoor login. Please log in manually...")
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.abspath("./playwright_glassdoor_session")
            
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir)
                except Exception:
                    pass
                    
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]

            context = None
            # 1. Try launching with system Google Chrome if present
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    channel="chrome",
                    args=browser_args,
                    ignore_default_args=["--enable-automation"],
                    user_agent=DEFAULT_MAC_UA,
                    viewport={"width": 1280, "height": 800}
                )
            except Exception:
                # 2. If Chrome is not installed, use Playwright's bundled Chromium with stealth
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    args=browser_args,
                    ignore_default_args=["--enable-automation"],
                    user_agent=DEFAULT_MAC_UA,
                    viewport={"width": 1280, "height": 800}
                )
                
            # Apply stealth evasions on the browser context
            context.add_init_script(STEALTH_JS)
            
            page = context.pages[0] if context.pages else context.new_page()
            user_agent = DEFAULT_MAC_UA
            
            page.goto("https://www.glassdoor.com/member/profile/login", wait_until="domcontentloaded")
            
            print("Waiting for login... (Complete login in the browser window)")
            
            detected = False
            for _ in range(150):
                cookies = context.cookies()
                has_auth_token = any(c['name'] in ('at', 'as_at', 'GD_SESSION_ID', 'gdId') for c in cookies)
                
                # Also verify if user was redirected past login
                current_url = page.url.lower()
                redirected_to_member = (
                    "glassdoor.com" in current_url
                    and not any(x in current_url for x in ["member/profile/login", "/login", "security", "__cf_chl"])
                    and any(x in current_url for x in ["/job", "/member", "/feed", "/community", "/reviews"])
                )
                
                if has_auth_token or redirected_to_member:
                    print("\n[INFO] Login successfully detected!")
                    detected = True
                    break
                time.sleep(2)
                
            if detected:
                cookies = context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                
                # Extract full storage state
                storage_state = context.storage_state()
                storage_state_str = json.dumps(storage_state)
                
                context.close()
                return cookie_str, user_agent, storage_state_str
            else:
                print("[ERROR] Login timeout or session cookies not found.")
                context.close()
                return None
    except Exception as e:
        print(f"[ERROR] Playwright execution failed: {e}")
        return None

def check_and_login_glassdoor():
    glassdoor_storage = os.getenv("GLASSDOOR_STORAGE_STATE")
    glassdoor_cookie = os.getenv("GLASSDOOR_COOKIE")
    glassdoor_ua = os.getenv("GLASSDOOR_USER_AGENT")
    
    if glassdoor_storage and glassdoor_storage.strip() and glassdoor_cookie and glassdoor_cookie.strip():
        # Session already exists, do not print anything
        return True

    print("\n" + "="*50)
    print("GLASSDOOR LOGIN & SESSION REQUIRED (AUTO-FLOW)")
    print("="*50)
    print("[INFO] Starting Playwright login browser automatically...")
    
    res = run_playwright_login()
    if res:
        import base64
        cookie_str, user_agent, storage_state_str = res
        storage_state_b64 = base64.b64encode(storage_state_str.encode("utf-8")).decode("utf-8")
        update_env_file("GLASSDOOR_COOKIE", f"'{cookie_str}'")
        update_env_file("GLASSDOOR_USER_AGENT", f"'{user_agent}'")
        update_env_file("GLASSDOOR_STORAGE_STATE", storage_state_b64)
        
        print("\n[SUCCESS] Glassdoor session and full storage state saved to .env!")
        load_dotenv(override=True)
        from src.config import Config
        Config.GLASSDOOR_COOKIE = os.getenv("GLASSDOOR_COOKIE")
        Config.GLASSDOOR_USER_AGENT = os.getenv("GLASSDOOR_USER_AGENT")
        Config.GLASSDOOR_STORAGE_STATE = os.getenv("GLASSDOOR_STORAGE_STATE")
        return True
    else:
        print("[WARNING] Glassdoor credentials save failed.")
        return False

if __name__ == "__main__":
    check_and_login_glassdoor()
