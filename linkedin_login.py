import os
import time
import sys
import shutil
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
            print("Please try manual login or install playwright manually.")
            return None

    print("\nOpening Real Chrome browser for LinkedIn login. Please log in manually...")
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.abspath("./playwright_linkedin_session")
            
            # Try to launch with real Google Chrome browser first to bypass Cloudflare
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
                # Fallback to webkit installation and launching
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
                
                context.close()
                return cookie_str, user_agent
            else:
                print("[ERROR] Login timeout or li_at cookie not found.")
                context.close()
                return None
    except Exception as e:
        print(f"[ERROR] Playwright execution failed: {e}")
        return None

def check_and_login():
    linkedin_cookie = os.getenv("LINKEDIN_COOKIE")
    linkedin_ua = os.getenv("LINKEDIN_USER_AGENT")
    
    force_login = False
    if linkedin_cookie and linkedin_cookie.strip() and linkedin_ua and linkedin_ua.strip():
        print("\nLinkedIn session credentials already exist in .env.")
        print("1. Use existing session (Default)")
        print("2. Login again / Update session credentials")
        try:
            choice = input("Option select kara (1/2, default 1): ").strip()
        except EOFError:
            choice = "1"
        if choice == "2":
            force_login = True
            # Clear Playwright session directories to wipe old cookies/cache
            session_dir = os.path.abspath("./playwright_linkedin_session")
            if os.path.exists(session_dir):
                print("[INFO] Clearing old browser session data...")
                try:
                    shutil.rmtree(session_dir)
                except Exception as e:
                    print(f"[Warning] Could not clear old session directory: {e}")
        else:
            return True

    print("\n" + "="*50)
    print("LINKEDIN LOGIN REQUIRED")
    print("="*50)
    print("1. Playwright Auto-Login (Real Chrome open karel)")
    print("2. Direct Cookie")
    
    try:
        choice = input("Option select kara (1/2, default 1): ").strip()
    except EOFError:
        choice = "1"
        
    if not choice:
        choice = "1"
        
    cookie_str = None
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    if choice == "1" and not force_login:
        session_dir = os.path.abspath("./playwright_linkedin_session")
        if os.path.exists(session_dir):
            try:
                shutil.rmtree(session_dir)
            except Exception:
                pass

    if choice == "1":
        res = run_playwright_login()
        if res:
            cookie_str, user_agent = res
    elif choice == "2":
        print("\n" + "-"*50)
        print("STEPS TO GET LINKEDIN COOKIE:")
        print("-"*50)
        print("1. Open your web browser (Chrome, Firefox, Safari, etc.).")
        print("2. Go to https://www.linkedin.com and log in to your account.")
        print("3. Press F12 (or right-click anywhere and select 'Inspect') to open Developer Tools.")
        print("4. Go to the 'Application' tab (on Chrome/Edge) or 'Storage' tab (on Firefox).")
        print("5. Under the left sidebar, expand 'Cookies' and select 'https://www.linkedin.com'.")
        print("6. Look for the cookie named 'li_at' in the list.")
        print("7. Double-click its Value, copy it, and paste it below.")
        print("-"*50)
        
        try:
            li_at = input("\nPlease paste the 'li_at' cookie value here: ").strip()
        except EOFError:
            li_at = ""
        if li_at:
            if "li_at=" in li_at:
                cookie_str = li_at
            else:
                cookie_str = f"li_at={li_at}"
            
    if cookie_str:
        update_env_file("LINKEDIN_COOKIE", f"'{cookie_str}'")
        update_env_file("LINKEDIN_USER_AGENT", f"'{user_agent}'")
        print("\n[SUCCESS] LinkedIn session .env madhe save zali aahe!")
        load_dotenv(override=True)
        from src.config import Config
        Config.LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE")
        Config.LINKEDIN_USER_AGENT = os.getenv("LINKEDIN_USER_AGENT", Config.LINKEDIN_USER_AGENT)
        return True
    else:
        print("[WARNING] LinkedIn credentials save nahi zale. Scraping guest mode madhe chalel.")
        return False

if __name__ == "__main__":
    check_and_login()
