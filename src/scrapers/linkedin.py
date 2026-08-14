import os
import re
import sys
import time
import base64
import json
import urllib.parse
from typing import List
from playwright.sync_api import sync_playwright

from src.config import Config
from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job
from src.tailor_cv.claude_client import ClaudeClient

try:
    from linkedin_login import check_and_login
except ImportError:
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.append(root_dir)
    from linkedin_login import check_and_login

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
        truncated_text = raw_text[:15000]
        response, _ = client._call_claude_api(system_prompt, truncated_text, temperature=0.2)
        return response.strip()
    except Exception as e:
        print(f"  [LLM Extraction Warning] Claude API call failed: {e}")
        return ""

@register_scraper
class LinkedInScraper(BaseScraper):
    def scrape(self, role: str, location: str, experience: str, limit: int = 10, start_offset: int = 0) -> List[Job]:
        print(f"\n[LinkedIn] Starting Playwright Scraper (Apply/Easy Apply Checker) for Role: '{role}', Location: '{location}' (Limit: {limit})")
        
        # 1. Verify LinkedIn login session
        try:
            if not check_and_login():
                print("[LinkedIn ERROR] Login verification failed. Please login manually first.")
                return []
        except Exception as e:
            print(f"[LinkedIn ERROR] Failed to run login verification: {e}")
            return []

        # Load storage state from env / config
        storage_state = None
        storage_state_env = Config.LINKEDIN_STORAGE_STATE
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
                    print(f"[LinkedIn ERROR] Error parsing storage state: {e}")

        if not storage_state:
            print("[LinkedIn ERROR] No storage state found in .env. Please run 'python linkedin_login.py' to login first.")
            return []

        scraped_jobs = []
        headless = True  # Scraper runs headless inside main CLI

        with sync_playwright() as p:
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
            if start_offset > 0:
                url += f"&start={start_offset}"
                
            print(f"[LinkedIn] Navigating to: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                if "login" in page.url:
                    print("[LinkedIn ERROR] Session expired! Run 'python linkedin_login.py' again.")
                    browser.close()
                    return []
                    
                page.wait_for_selector(
                    ".scaffold-layout__list-container, .jobs-search-results-list, li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]",
                    timeout=10000
                )
            except Exception as e:
                print(f"[LinkedIn WARNING] Selector wait timed out or failed: {e}")
                
            # Scroll down to load job cards
            try:
                pane = page.locator(".jobs-search-results-list, .jobs-search-results-list__container").first
                if pane.count() > 0:
                    print("[LinkedIn] Scrolling job list to load cards...")
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
                print(f"[LinkedIn ERROR] No job cards loaded: {e}")
                browser.close()
                return []
                
            card_locators = page.locator("li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]").all()
            print(f"[LinkedIn] Found {len(card_locators)} job cards on the search results page.")
            
            # Pre-classify and deduplicate cards to prioritize "Apply" over "Easy Apply"
            classified_cards = []
            seen_job_ids = set()
            for idx, card in enumerate(card_locators):
                try:
                    job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id")
                    if not job_id:
                        link = card.locator("a").first
                        href = link.get_attribute("href") if link.count() > 0 else ""
                        if "/jobs/view/" in href:
                            match = re.search(r"/jobs/view/(\d+)", href)
                            if match:
                                job_id = match.group(1)
                    
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
                        "job_id": job_id,
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
                curr_job_id = item["job_id"]
                
                try:
                    card.scroll_into_view_if_needed()
                    
                    # Extract title and company from the card
                    title_loc = card.locator(".job-card-list__title, .job-card-container__link, a.job-card-list__title").first
                    company_loc = card.locator(".job-card-container__company-name, .job-card-container__primary-description, .artdeco-entity-lockup__subtitle").first
                    
                    title = title_loc.inner_text().strip() if title_loc.count() > 0 else "Unknown Title"
                    title = title.replace("\n", " ")
                    company = company_loc.inner_text().strip().split("\n")[0] if company_loc.count() > 0 else "Unknown Company"
                    
                    print(f"\n({count+1}/{limit}) Clicking card for: '{title}' at '{company}'")
                    
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
                        detail_pane = page.locator(".jobs-search-results-list__detail-pane, .jobs-details").first
                        if detail_pane.count() > 0:
                            apply_nested = detail_pane.locator("button:has-text('Easy Apply'), button:has-text('Apply'), a:has-text('Easy Apply'), a:has-text('Apply')").first
                            if apply_nested.count() > 0 and apply_nested.is_visible():
                                apply_button = apply_nested
                                button_text = apply_nested.inner_text().strip().replace("\n", " ")
                                button_found = True
                                
                    button_type = "Not Found"
                    if "easy apply" in button_text.lower():
                        button_type = "Easy Apply"
                    elif "apply" in button_text.lower():
                        button_type = "Apply"
                        
                    job_url = f"https://www.linkedin.com/jobs/view/{curr_job_id}" if curr_job_id else url
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
                             href_val = None
                             try:
                                 tag_name = apply_button.evaluate("el => el.tagName")
                                 if tag_name.lower() == "a":
                                     href_val = apply_button.get_attribute("href")
                             except Exception:
                                 pass
                                 
                             new_page = None
                             try:
                                 with context.expect_page(timeout=10000) as new_page_info:
                                     apply_button.click(force=True)
                                 new_page = new_page_info.value
                                 new_page.wait_for_load_state("domcontentloaded", timeout=12000)
                                 time.sleep(2)
                             except Exception as click_err:
                                 if href_val:
                                     print(f"    [Click Timeout] Navigating directly to external href: {href_val}")
                                     new_page = context.new_page()
                                     new_page.goto(href_val, wait_until="domcontentloaded", timeout=15000)
                                     time.sleep(2)
                                 else:
                                     raise click_err
                                     
                             if new_page:
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
                                 
                                 if raw_text:
                                     print("    [LLM] Extracting JD from career page...")
                                     extracted_jd = extract_jd_via_llm(raw_text)
                                     if extracted_jd:
                                         extracted_status = "✓"
                                     else:
                                         extracted_jd = raw_text[:2000]
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
                    
                    if not extracted_jd:
                        extracted_jd = f"Job title: {title}. Company: {company}. Location: {location}. Link: {final_url}"
                        
                    salary = None
                    salary_elem = page.locator(".job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight").first
                    if salary_elem.count() > 0 and salary_elem.is_visible():
                        text = salary_elem.inner_text()
                        if "$" in text or "₹" in text or "£" in text or "€" in text:
                            salary = text.strip()
                            
                    job_obj = Job(
                        title=title,
                        company=company,
                        location=location,
                        about_job=extracted_jd,
                        site=["LinkedIn"],
                        url=final_url,
                        salary=salary,
                        job_id=curr_job_id
                    )
                    scraped_jobs.append(job_obj)
                    count += 1
                    
                except Exception as card_err:
                    print(f"  [ERROR] Failed to process card: {card_err}")
                    
            browser.close()
            
        print(f"[LinkedIn] Completed. Scraped {len(scraped_jobs)} jobs.")
        return scraped_jobs
