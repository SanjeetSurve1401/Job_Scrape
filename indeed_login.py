import os
import time
import sys
import shutil
import webbrowser
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

    print("\nOpening Real Chrome browser for Indeed login. Please log in manually...")
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.abspath("./playwright_indeed_session")
            
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"]
                )
            except Exception as e:
                print(f"[INFO] Real Chrome could not be launched ({e}). Falling back to WebKit...")
                import subprocess
                subprocess.run([sys.executable, "-m", "playwright", "install", "webkit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                context = p.webkit.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False
                )
                
            page = context.pages[0] if context.pages else context.new_page()
            
            try:
                user_agent = page.evaluate("navigator.userAgent")
            except Exception:
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0"
                
            page.goto("https://secure.indeed.com/auth")
            
            print("Waiting for login... (Complete login in the browser window)")
            
            detected = False
            for _ in range(150): # 5 minutes max
                current_url = page.url
                cookies = context.cookies()
                
                # Check if user has redirected away from auth/login pages and cookies are set
                is_logged_in_url = "secure.indeed.com/auth" not in current_url and "secure.indeed.com/account/login" not in current_url and "indeed.com" in current_url
                
                if is_logged_in_url and cookies:
                    print("\n[INFO] Login successfully detected!")
                    detected = True
                    break
                time.sleep(2)
                
            if detected:
                cookies = context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                context.close()
                return cookie_str, user_agent
            else:
                print("[ERROR] Login timeout or session cookies not found.")
                context.close()
                return None
    except Exception as e:
        print(f"[ERROR] Playwright execution failed: {e}")
        return None

def check_and_login_indeed():
    indeed_cookie = os.getenv("INDEED_COOKIE")
    indeed_ua = os.getenv("INDEED_USER_AGENT")
    
    force_login = False
    if indeed_cookie and indeed_cookie.strip() and indeed_ua and indeed_ua.strip():
        print("\nIndeed session credentials already exist in .env.")
        print("1. Use existing session (Default)")
        print("2. Login again / Update session credentials")
        try:
            choice = input("Option select kara (1/2, default 1): ").strip()
        except EOFError:
            choice = "1"
        if choice == "2":
            force_login = True
            # Clear Playwright session directories to wipe old cookies/cache
            session_dir = os.path.abspath("./playwright_indeed_session")
            if os.path.exists(session_dir):
                print("[INFO] Clearing old browser session data...")
                try:
                    shutil.rmtree(session_dir)
                except Exception as e:
                    print(f"[Warning] Could not clear old session directory: {e}")
        else:
            return True

    print("\n" + "="*50)
    print("INDEED LOGIN & SESSION REQUIRED")
    print("="*50)
    print("[INFO] Playwright Auto-Login start hot aahe (Real Chrome open karel)...")
    
    cookie_str = None
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0"
    
    if not force_login:
        session_dir = os.path.abspath("./playwright_indeed_session")
        if os.path.exists(session_dir):
            try:
                shutil.rmtree(session_dir)
            except Exception:
                pass

    res = run_playwright_login()
    if res:
        cookie_str, user_agent = res
        
    if cookie_str and user_agent:
        update_env_file("INDEED_COOKIE", f"'{cookie_str}'")
        update_env_file("INDEED_USER_AGENT", f"'{user_agent}'")
        print("\n[SUCCESS] Indeed session .env madhe save zali aahe!")
        load_dotenv(override=True)
        from src.config import Config
        Config.INDEED_COOKIE = os.getenv("INDEED_COOKIE")
        Config.INDEED_USER_AGENT = os.getenv("INDEED_USER_AGENT")
        return True
    else:
        print("[WARNING] Indeed credentials save nahi zale. Scraping check fail hoil.")
        return False

if __name__ == "__main__":
    check_and_login_indeed()
