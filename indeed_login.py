import os
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

def check_and_login_indeed():
    indeed_cookie = os.getenv("INDEED_COOKIE")
    indeed_ua = os.getenv("INDEED_USER_AGENT")
    
    if indeed_cookie and indeed_cookie.strip() and indeed_ua and indeed_ua.strip():
        return True

    print("\n" + "="*50)
    print("INDEED LOGIN & SESSION REQUIRED")
    print("="*50)
    print("Tumcha default browser open kela jaat aahe. Indeed var search/login kara.")
    
    # Open browser to Indeed
    webbrowser.open("https://in.indeed.com")
    
    print("\nLogin kelya nantar:")
    print("1. Browser madhe Developer Tools (F12 kiwa Right-Click -> Inspect) open kara.")
    print("2. Network tab click kara ani indeed.com chi kontihi request select kara.")
    print("3. Request Headers madhe 'Cookie' ani 'User-Agent' shodha.")
    
    try:
        cookie_val = input("\nCopy keli-leli 'Cookie' string ithe paste kara: ").strip()
        ua_val = input("Copy kela-lela 'User-Agent' string ithe paste kara: ").strip()
    except EOFError:
        cookie_val = ""
        ua_val = ""
        
    if cookie_val and ua_val:
        update_env_file("INDEED_COOKIE", f"'{cookie_val}'")
        update_env_file("INDEED_USER_AGENT", f"'{ua_val}'")
        print("\n[SUCCESS] Indeed session .env madhe save zali aahe!")
        load_dotenv(override=True)
        from src.config import Config
        Config.INDEED_COOKIE = os.getenv("INDEED_COOKIE")
        Config.INDEED_USER_AGENT = os.getenv("INDEED_USER_AGENT")
        return True
    else:
        print("[WARNING] Credentials empty ahet. Scraping check fail hoil.")
        return False

if __name__ == "__main__":
    check_and_login_indeed()
