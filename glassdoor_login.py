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

    print("\nOpening Real Chrome browser for Glassdoor login. Please log in manually...")
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.abspath("./playwright_glassdoor_session")
            
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
            
            # Fetch user agent immediately to avoid navigation context destruction issues
            try:
                user_agent = page.evaluate("navigator.userAgent")
            except Exception:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                
            page.goto("https://www.glassdoor.com/member/profile/login")
            
            print("Waiting for login... (Complete login in the browser window)")
            
            detected = False
            for _ in range(150): # 5 minutes max
                cookies = context.cookies()
                
                # Check for the auth token cookie 'at'
                has_auth_token = any(c['name'] == 'at' for c in cookies)
                
                if has_auth_token:
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

def check_and_login_glassdoor():
    glassdoor_cookie = os.getenv("GLASSDOOR_COOKIE")
    glassdoor_ua = os.getenv("GLASSDOOR_USER_AGENT")
    
    force_login = False
    if glassdoor_cookie and glassdoor_cookie.strip() and glassdoor_ua and glassdoor_ua.strip():
        print("\nGlassdoor session credentials already exist in .env.")
        print("1. Use existing session (Default)")
        print("2. Login again / Update session credentials")
        try:
            choice = input("Option select kara (1/2, default 1): ").strip()
        except EOFError:
            choice = "1"
        if choice == "2":
            force_login = True
            # Clear Playwright session directories to wipe old cookies/cache
            session_dir = os.path.abspath("./playwright_glassdoor_session")
            if os.path.exists(session_dir):
                print("[INFO] Clearing old browser session data...")
                try:
                    shutil.rmtree(session_dir)
                except Exception as e:
                    print(f"[Warning] Could not clear old session directory: {e}")
        else:
            return True

    print("\n" + "="*50)
    print("GLASSDOOR LOGIN & SESSION REQUIRED")
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
    
    # If starting a fresh Playwright run, make sure old session is wiped if force_login was selected
    if choice == "1" and not force_login:
        # Wipe session directory to avoid false detection of old session
        session_dir = os.path.abspath("./playwright_glassdoor_session")
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
        print("STEPS TO SET GLASSDOOR COOKIES DIRECTLY IN .ENV:")
        print("-"*50)
        print("1. Open your web browser (Chrome, Firefox, Safari, etc.).")
        print("2. Go to https://www.glassdoor.com and log in to your account.")
        print("3. Press F12 (or right-click anywhere and select 'Inspect') to open Developer Tools.")
        print("4. Go to the 'Network' tab and reload the page.")
        print("5. Select any request to a glassdoor.com domain (e.g. 'jobs.htm' or 'index.htm').")
        print("6. In the right pane, look at the 'Request Headers' section.")
        print("7. Find the 'Cookie' header and copy its entire value.")
        print("8. Open the '.env' file in this project folder.")
        print("9. Paste the copied cookie value inside the single quotes of GLASSDOOR_COOKIE='...' (Also set GLASSDOOR_USER_AGENT if needed)")
        print("10. Save the '.env' file.")
        print("-"*50)
        print("\n[INFO] Terminal freeze avoid karanyasathi direct terminal input disable kela aahe.")
        
        while True:
            try:
                input("\nKrupaya '.env' file edit kara ani ready zalya-var [ENTER] press kara to proceed...")
            except EOFError:
                pass
            
            # Reload .env and verify all required variables
            load_dotenv(override=True)
            cookie_str = os.getenv("GLASSDOOR_COOKIE")
            user_agent = os.getenv("GLASSDOOR_USER_AGENT")
            groq_api = os.getenv("GROQ_API")
            
            errors = []
            if not cookie_str or not cookie_str.strip() or "paste_here" in cookie_str:
                errors.append("GLASSDOOR_COOKIE is empty or not set correctly.")
            if not user_agent or not user_agent.strip():
                errors.append("GLASSDOOR_USER_AGENT is empty or missing.")
            if not groq_api or not groq_api.strip():
                errors.append("GROQ_API is missing from .env.")
                
            if errors:
                print("\n" + "="*50)
                print("[ERROR] .env Validation Failed:")
                for err in errors:
                    print(f"  - {err}")
                print("="*50)
                print("Krupaya variables thik kara ani parat enter press kara.")
            else:
                print("\n[SUCCESS] .env validation successful! Glassdoor credentials loaded.")
                break
            
    if cookie_str and user_agent:
        if choice == "1":
            update_env_file("GLASSDOOR_COOKIE", f"'{cookie_str}'")
            update_env_file("GLASSDOOR_USER_AGENT", f"'{user_agent}'")
            print("\n[SUCCESS] Glassdoor session .env madhe save zali aahe!")
            
        load_dotenv(override=True)
        from src.config import Config
        Config.GLASSDOOR_COOKIE = os.getenv("GLASSDOOR_COOKIE")
        Config.GLASSDOOR_USER_AGENT = os.getenv("GLASSDOOR_USER_AGENT")
        return True
    else:
        print("[WARNING] Credentials empty ahet. Scraping check fail hoil.")
        return False

if __name__ == "__main__":
    check_and_login_glassdoor()
