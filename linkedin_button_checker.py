import os
import re
import sys
import time
import argparse
import urllib.parse
import json
import base64
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Ensure root directory is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from linkedin_login import check_and_login
from src.config import Config
from src.tailor_cv.claude_client import ClaudeClient
from datetime import datetime, timezone

def extract_jd_via_llm(raw_text: str) -> str:
    """Extract structured job description from raw webpage text using Claude API."""
    if not raw_text or not raw_text.strip():
        return ""
    try:
        client = ClaudeClient()
        system_prompt = (
            "You are an expert technical recruiter. Extract the clean, structured Job Description "
            "(responsibilities, requirements, qualifications, and benefits) from the raw text of a career site webpage. "
            "Remove all website boilerplate, navigation links, login elements, cookie notices, or generic ads. "
            "Return only the clean extracted job description directly. No greeting, no markdown wrappers, no introduction."
        )
        # Limit text length to avoid token limits
        truncated_text = raw_text[:15000]
        response, _ = client._call_claude_api(system_prompt, truncated_text, temperature=0.2)
        return response.strip()
    except Exception as e:
        print(f"  [LLM Extraction Warning] Claude API call failed: {e}")
        return ""

def rgb_to_hex(rgb_str):
    """Convert rgb(r, g, b) or rgba(r, g, b, a) to #RRGGBB hex format."""
    if not rgb_str:
        return "Unknown"
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)", rgb_str)
    if match:
        r, g, b = map(int, match.groups())
        return f"#{r:02X}{g:02X}{b:02X}"
    return rgb_str

def check_linkedin_buttons(role: str, location: str, limit: int = 5, headless: bool = False):
    print(f"\n[LinkedIn Checker] Starting search for: '{role}' in '{location}' (Limit: {limit})")
    
    # 1. Verify LinkedIn login session
    if not check_and_login():
        print("[LinkedIn Checker ERROR] Login verification failed. Please login manually first.")
        return
        
    # Reload config in case env file was updated
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    storage_state_env = os.getenv("LINKEDIN_STORAGE_STATE")
    storage_state = None
    if storage_state_env and storage_state_env.strip():
        try:
            decoded = base64.b64decode(storage_state_env, validate=True).decode("utf-8")
            storage_state = json.loads(decoded)
        except Exception:
            try:
                if (storage_state_env.startswith("'") and storage_state_env.endswith("'")) or \
                   (storage_state_env.startswith('"') and storage_state_env.endswith('"')):
                    storage_state_env = storage_state_env[1:-1]
                storage_state = json.loads(storage_state_env)
            except Exception as e:
                print(f"[LinkedIn Checker ERROR] Error parsing storage state: {e}")
                
    if not storage_state:
        print("[LinkedIn Checker ERROR] No storage state found. Please run 'python linkedin_login.py' to login first.")
        return

    target_color_hex = "#0A66C2"
    results = []

    with sync_playwright() as p:
        print("[LinkedIn Checker] Launching browser...")
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=storage_state,
            user_agent=Config.LINKEDIN_USER_AGENT
        )
        page = context.new_page()
        
        # Build search URL
        query_role = urllib.parse.quote(role)
        query_loc = urllib.parse.quote(location)
        url = f"https://www.linkedin.com/jobs/search/?keywords={query_role}&location={query_loc}"
        
        print(f"[LinkedIn Checker] Navigating to: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            
            if "login" in page.url:
                print("[LinkedIn Checker ERROR] Session expired! Run 'python linkedin_login.py' again.")
                browser.close()
                return
                
            page.wait_for_selector(
                ".scaffold-layout__list-container, .jobs-search-results-list, li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]",
                timeout=10000
            )
        except Exception as e:
            print(f"[LinkedIn Checker WARNING] Selector wait timed out or failed: {e}")
            
        # Scroll down to load job cards
        try:
            pane = page.locator(".jobs-search-results-list, .jobs-search-results-list__container").first
            if pane.count() > 0:
                print("[LinkedIn Checker] Scrolling job list to load cards...")
                for _ in range(3):
                    pane.evaluate("el => el.scrollTop = el.scrollHeight")
                    page.wait_for_timeout(1000)
        except Exception:
            pass
            
        # Wait for job cards to load
        try:
            page.wait_for_selector(
                "li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]",
                timeout=15000
            )
        except Exception as e:
            print(f"[LinkedIn Checker ERROR] No job cards loaded: {e}")
            browser.close()
            return
            
        card_locators = page.locator("li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]").all()
        print(f"[LinkedIn Checker] Found {len(card_locators)} job cards on the search results page.")
        
        # Pre-classify and deduplicate cards to prioritize "Apply" over "Easy Apply"
        classified_cards = []
        seen_job_ids = set()
        for idx, card in enumerate(card_locators):
            try:
                # Extract job ID for deduplication
                job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id")
                if not job_id:
                    link = card.locator("a").first
                    href = link.get_attribute("href") if link.count() > 0 else ""
                    if "/jobs/view/" in href:
                        match = re.search(r"/jobs/view/(\d+)", href)
                        if match:
                            job_id = match.group(1)
                
                # Use inner text hash if job_id is not found
                if not job_id:
                    job_id = card.inner_text().strip()
                    
                if job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                
                card_text = card.inner_text().lower()
                is_easy_apply = "easy apply" in card_text
                classified_cards.append({
                    "locator": card,
                    "is_easy_apply": is_easy_apply,
                    "orig_index": idx
                })
            except Exception:
                pass
                
        # Sort: False (Apply) first, True (Easy Apply) second
        classified_cards.sort(key=lambda x: x["is_easy_apply"])
        
        count = 0
        for item in classified_cards:
            if count >= limit:
                break
                
            card = item["locator"]
            is_easy = item["is_easy_apply"]
            
            try:
                # Scroll card into view
                card.scroll_into_view_if_needed()
                
                # Extract title and company from the card
                title_loc = card.locator(".job-card-list__title, .job-card-container__link, a.job-card-list__title").first
                company_loc = card.locator(".job-card-container__company-name, .job-card-container__primary-description, .artdeco-entity-lockup__subtitle").first
                
                title = title_loc.inner_text().strip() if title_loc.count() > 0 else "Unknown Title"
                title = title.replace("\n", " ")
                company = company_loc.inner_text().strip().split("\n")[0] if company_loc.count() > 0 else "Unknown Company"
                
                print(f"\n({count+1}/{limit}) Clicking card for: '{title}' at '{company}'")
                
                # Click the card to open details on the right
                card.click()
                page.wait_for_timeout(3000)
                
                # Locate the apply button inside details pane
                btn_selectors = [
                    ".jobs-search-results-list__detail-pane button.jobs-apply-button",
                    ".jobs-search-results-list__detail-pane a.jobs-apply-button",
                    ".jobs-details button.jobs-apply-button",
                    ".jobs-details a.jobs-apply-button",
                    "button.jobs-apply-button",
                    "a.jobs-apply-button"
                ]
                
                button_found = False
                button_text = "Not Found"
                apply_button = None
                
                for sel in btn_selectors:
                    locator = page.locator(sel).first
                    if locator.count() > 0 and locator.is_visible():
                        apply_button = locator
                        button_text = locator.inner_text().strip().replace("\n", " ")
                        button_found = True
                        break
                        
                if not button_found:
                    # Let's check for any apply/easy apply text on buttons/links in details pane
                    detail_pane = page.locator(".jobs-search-results-list__detail-pane, .jobs-details").first
                    if detail_pane.count() > 0:
                        apply_nested = detail_pane.locator("button:has-text('Easy Apply'), button:has-text('Apply'), a:has-text('Easy Apply'), a:has-text('Apply')").first
                        if apply_nested.count() > 0 and apply_nested.is_visible():
                            apply_button = apply_nested
                            button_text = apply_nested.inner_text().strip().replace("\n", " ")
                            button_found = True
                            
                # Normalize button type string
                button_type = "Not Found"
                if "easy apply" in button_text.lower():
                    button_type = "Easy Apply"
                elif "apply" in button_text.lower():
                    button_type = "Apply"
                    
                # Try to extract the job's direct URL from the card's link
                job_url = url
                try:
                    link_loc = card.locator("a").first
                    href = link_loc.get_attribute("href") if link_loc.count() > 0 else ""
                    if href:
                        if not href.startswith("http"):
                            href = urllib.parse.urljoin("https://www.linkedin.com", href)
                        parsed_url = urllib.parse.urlparse(href)
                        job_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                except Exception:
                    pass

                clicked_status = "N/A"
                extracted_status = "✗"
                extracted_jd = ""
                final_url = job_url
                
                # If Apply (external), click it to extract JD from career page
                if button_type == "Apply" and apply_button:
                    clicked_status = "✗"
                    try:
                         # Get href as fallback before click
                         href_val = None
                         try:
                             tag_name = apply_button.evaluate("el => el.tagName")
                             if tag_name.lower() == "a":
                                 href_val = apply_button.get_attribute("href")
                         except Exception:
                             pass
                             
                         # Try clicking and expecting a new tab
                         new_page = None
                         try:
                             with context.expect_page(timeout=10000) as new_page_info:
                                 apply_button.click(force=True)
                             new_page = new_page_info.value
                             new_page.wait_for_load_state("domcontentloaded", timeout=12000)
                             time.sleep(2)
                         except Exception as click_err:
                             # Fallback: open a new page and go to href directly if we have it
                             if href_val:
                                 print(f"    [Click Timeout] Navigating directly to external href: {href_val}")
                                 new_page = context.new_page()
                                 new_page.goto(href_val, wait_until="domcontentloaded", timeout=15000)
                                 time.sleep(2)
                             else:
                                 raise click_err
                                 
                         if new_page:
                             # Auto-accept cookies if any consent dialog/button is present
                             try:
                                 cookie_selectors = [
                                     "button:has-text('Accept Cookies')",
                                     "button:has-text('Accept all')",
                                     "button:has-text('Accept All')",
                                     "button:has-text('Accept')",
                                     "button:has-text('Allow All')",
                                     "button:has-text('Allow all')",
                                     "button:has-text('Agree')",
                                     "button:has-text('I Agree')",
                                     "button:has-text('Allow Cookies')",
                                     "a:has-text('Accept Cookies')",
                                     "a:has-text('Accept all')",
                                     "a:has-text('Accept All')",
                                     "a:has-text('Accept')",
                                     "a:has-text('Agree')"
                                 ]
                                 for selector in cookie_selectors:
                                     cookie_btn = new_page.locator(selector).first
                                     if cookie_btn.count() > 0 and cookie_btn.is_visible():
                                         print(f"    [Cookies] Clicking consent button: '{cookie_btn.inner_text().strip()}'")
                                         cookie_btn.click(timeout=3000)
                                         time.sleep(1)
                                         break
                             except Exception:
                                 pass

                             raw_text = new_page.locator("body").inner_text(timeout=10000).strip()
                             final_url = new_page.url
                             clicked_status = "✓"
                             new_page.close()
                             
                             # LLM Extraction
                             if raw_text:
                                 print("    [LLM] Extracting JD from career page...")
                                 extracted_jd = extract_jd_via_llm(raw_text)
                                 if extracted_jd:
                                     extracted_status = "✓"
                                 else:
                                     extracted_jd = raw_text[:2000] # Fallback to raw text snippet
                             else:
                                 print("    [Warning] Career page body text is empty.")
                                 
                    except Exception as ext_err:
                        print(f"    [ERROR] External career page extraction failed: {ext_err}")
                         
                # If Easy Apply, extract JD from LinkedIn directly
                elif button_type == "Easy Apply":
                    try:
                        desc_elem = page.locator(".jobs-description__content, .jobs-description-content__text, div#job-details").first
                        if desc_elem.count() > 0 and desc_elem.is_visible():
                            extracted_jd = desc_elem.inner_text().strip()
                        else:
                            detail_pane = page.locator(".jobs-search-results-list__detail-pane, .jobs-details").first
                            if detail_pane.count() > 0:
                                extracted_jd = detail_pane.inner_text().strip()
                                
                        if extracted_jd:
                            extracted_status = "✓"
                    except Exception as ext_err:
                        print(f"    [ERROR] Easy Apply extraction failed: {ext_err}")
                        
                print(f"  Button Detected: {button_text} (Normalized: {button_type})")
                print(f"  Clicked: {clicked_status}")
                print(f"  JD Extracted: {extracted_status}")
                
                results.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "button_type": button_type,
                    "clicked": clicked_status,
                    "jd_extracted": extracted_status,
                    "about_job": extracted_jd,
                    "url": final_url
                })
                
                count += 1
                
            except Exception as card_err:
                print(f"  [ERROR] Failed to process card: {card_err}")
                
        # Close browser
        browser.close()
        
        # Save results to JSON file inside the outputs folder
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, "linkedin_scraped_jobs.json")
        try:
            formatted_results = []
            for idx, res in enumerate(results, 1):
                # Format to match the original database/Job schema without ticks/crosses
                formatted_results.append({
                    "sr_no": idx,
                    "title": res["title"],
                    "company": res["company"],
                    "location": res["location"],
                    "about_job": res["about_job"],
                    "site": "LinkedIn",
                    "url": res["url"],
                    "salary": None,
                    "experience_required": None,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "job_id": None,
                    "score": None,
                    "explanation": None,
                    "ats_score": None,
                    "tokens_consumed": None
                })
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(formatted_results, f, indent=2, ensure_ascii=False)
            print(f"\n[LinkedIn Checker] Successfully saved {len(formatted_results)} results to '{output_file}'")
        except Exception as json_err:
            print(f"\n[LinkedIn Checker ERROR] Failed to save JSON file: {json_err}")
        
    # Print the new summary table
    print("\n" + "="*95)
    print("                              LINKEDIN JD EXTRACTION SUMMARY")
    print("="*95)
    print(f"{'Sr. No':<6} | {'Company':<20} | {'Job Title':<30} | {'Button Type':<12} | {'Clicked':<7} | {'JD Extracted'}")
    print("-"*95)
    for idx, res in enumerate(results, 1):
        company = res['company'][:18] + '..' if len(res['company']) > 20 else res['company']
        title = res['title'][:28] + '..' if len(res['title']) > 30 else res['title']
        print(f"{idx:<6} | {company:<20} | {title:<30} | {res['button_type']:<12} | {res['clicked']:<7} | {res['jd_extracted']}")
    print("="*95)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Apply/Easy Apply Button & Color Checker")
    parser.add_argument("--role", type=str, default="Python Developer", help="Job role to search for (default: 'Python Developer')")
    parser.add_argument("--location", type=str, default="India", help="Job location to search for (default: 'India')")
    parser.add_argument("--limit", type=int, default=5, help="Number of jobs to verify (default: 5)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default is headful)")
    
    args = parser.parse_args()
    check_linkedin_buttons(role=args.role, location=args.location, limit=args.limit, headless=args.headless)
