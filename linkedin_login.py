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

    print("\nOpening Real Chrome browser for LinkedIn login. Please log in manually...")
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.abspath("./playwright_linkedin_session")
            
            # Wipe old session data to force clean login screen if login runs
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir)
                except Exception:
                    pass
                    
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"]
                )
            except Exception as e:
                print(f"[INFO] Real Chrome could not be launched ({e}). Falling back to default WebKit...")
                import subprocess
                subprocess.run([sys.executable, "-m", "playwright", "install", "webkit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                context = p.webkit.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False
                )
                
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.linkedin.com/login")
            
            li_at_cookie = None
            jsessionid = None
            user_agent = page.evaluate("navigator.userAgent")
            
            print("Waiting for login... (Complete login in the browser window)")
            for _ in range(150):
                cookies = context.cookies()
                for cookie in cookies:
                    if cookie['name'] == 'li_at':
                        li_at_cookie = cookie['value']
                    if cookie['name'] == 'JSESSIONID':
                        jsessionid = cookie['value']
                if li_at_cookie:
                    break
                time.sleep(2)
                
            if li_at_cookie:
                cookie_str = f"li_at={li_at_cookie}"
                if jsessionid:
                    cookie_str += f"; JSESSIONID={jsessionid}"
                
                other_cookies = [f"{c['name']}={c['value']}" for c in cookies if c['name'] not in ('li_at', 'JSESSIONID')]
                if other_cookies:
                    cookie_str += "; " + "; ".join(other_cookies)
                
                # Extract full storage state
                storage_state = context.storage_state()
                storage_state_str = json.dumps(storage_state)
                
                context.close()
                return cookie_str, user_agent, storage_state_str
            else:
                print("[ERROR] Login timeout or li_at cookie not found.")
                context.close()
                return None
    except Exception as e:
        print(f"[ERROR] Playwright execution failed: {e}")
        return None

def check_and_login():
    linkedin_storage = os.getenv("LINKEDIN_STORAGE_STATE")
    linkedin_cookie = os.getenv("LINKEDIN_COOKIE")
    linkedin_ua = os.getenv("LINKEDIN_USER_AGENT")
    
    if linkedin_storage and linkedin_storage.strip() and linkedin_cookie and linkedin_cookie.strip():
        print("\nLinkedIn session credentials already exist in .env.")
        return True

    print("\n" + "="*50)
    print("LINKEDIN LOGIN REQUIRED (AUTO-FLOW)")
    print("="*50)
    print("[INFO] Starting Playwright login browser automatically...")
    
    res = run_playwright_login()
    if res:
        cookie_str, user_agent, storage_state_str = res
        update_env_file("LINKEDIN_COOKIE", f"'{cookie_str}'")
        update_env_file("LINKEDIN_USER_AGENT", f"'{user_agent}'")
        update_env_file("LINKEDIN_STORAGE_STATE", f"'{storage_state_str}'")
        
        print("\n[SUCCESS] LinkedIn session and full storage state saved to .env!")
        load_dotenv(override=True)
        from src.config import Config
        Config.LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE")
        Config.LINKEDIN_USER_AGENT = os.getenv("LINKEDIN_USER_AGENT", Config.LINKEDIN_USER_AGENT)
        Config.LINKEDIN_STORAGE_STATE = os.getenv("LINKEDIN_STORAGE_STATE")
        return True
    else:
        print("[WARNING] LinkedIn credentials save failed.")
        return False

if __name__ == "__main__":
    check_and_login()
