import os
import time
import re
import json
import urllib.parse
from typing import List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from src.config import Config
from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job

@register_scraper
class LinkedInScraper(BaseScraper):
    def scrape(self, role: str, location: str, experience: str, limit: int = 10, start_offset: int = 0) -> List[Job]:
        print(f"\n[LinkedIn] Starting Playwright Scraper for Role: '{role}', Location: '{location}' (Limit: {limit}, Offset: {start_offset})")
        scraped_jobs = []
        
        # Load storage state from Config
        storage_state = None
        storage_state_env = Config.LINKEDIN_STORAGE_STATE
        if storage_state_env and storage_state_env.strip():
            try:
                import base64
                try:
                    decoded = base64.b64decode(storage_state_env, validate=True).decode("utf-8")
                    storage_state = json.loads(decoded)
                except Exception:
                    if (storage_state_env.startswith("'") and storage_state_env.endswith("'")) or \
                       (storage_state_env.startswith('"') and storage_state_env.endswith('"')):
                        storage_state_env = storage_state_env[1:-1]
                    storage_state = json.loads(storage_state_env)
            except Exception:
                print("[LinkedIn] Storage state in .env is invalid or outdated. Please run 'python linkedin_login.py' to login again.")
                
        user_data_dir = os.path.abspath("./playwright_linkedin_session")
        
        with sync_playwright() as p:
            browser = None
            context = None
            
            try:
                if storage_state:
                    # Use storage state in a clean browser session
                    # This prevents directory locking conflicts when running multiple tasks
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=storage_state,
                        user_agent=Config.LINKEDIN_USER_AGENT
                    )
                else:
                    # Fallback to persistent context folder
                    if not os.path.exists(user_data_dir):
                        print("[LinkedIn ERROR] No storage state in .env or session directory found! Run linkedin_login.py first.")
                        return []
                    # Silenced persistent session print
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=True,
                        channel="chrome",
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--enable-automation"]
                    )
            except Exception as e:
                print(f"[LinkedIn ERROR] Could not launch Playwright browser session: {e}")
                return []
            
            page = context.pages[0] if context.pages else context.new_page()
            
            # Go to LinkedIn job search page
            query_role = urllib.parse.quote(role)
            query_loc = urllib.parse.quote(location)
            url = f"https://www.linkedin.com/jobs/search/?keywords={query_role}&location={query_loc}"
            if start_offset > 0:
                url += f"&start={start_offset}"
            
            print(f"[LinkedIn] Navigating to: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                # Check if we are redirected to login page or if we are logged in
                if "login" in page.url:
                    print("[LinkedIn ERROR] Session expired or not logged in! Run linkedin_login.py to update session.")
                    if browser:
                        browser.close()
                    else:
                        context.close()
                    return []
                
                page.wait_for_selector(
                    ".scaffold-layout__list-container, .jobs-search-results-list, li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]",
                    timeout=5000
                )
            except Exception as e:
                pass
                
            # Scroll the job list pane to load more items
            try:
                pane_selector = ".jobs-search-results-list, .jobs-search-results-list__container"
                pane = page.locator(pane_selector).first
                if pane.count() > 0:
                    print("[LinkedIn] Scrolling job list to load more jobs...")
                    for _ in range(5):
                        pane.evaluate("el => el.scrollTop = el.scrollHeight")
                        page.wait_for_timeout(1000)
            except Exception as scroll_error:
                pass

            # Extract job cards
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Select job items
            cards = soup.select("li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id]")
            print(f"[LinkedIn] Found {len(cards)} raw job cards in HTML.")
            
            parsed_jobs_info = []
            for card in cards:
                if len(parsed_jobs_info) >= limit:
                    break
                    
                try:
                    link_elem = card.find("a", href=True)
                    if not link_elem:
                        continue
                        
                    href = link_elem["href"]
                    # Extract job ID
                    job_id = ""
                    if "/jobs/view/" in href:
                        match = re.search(r"/jobs/view/(\d+)", href)
                        if match:
                            job_id = match.group(1)
                    if not job_id and card.has_attr("data-occludable-job-id"):
                        job_id = card["data-occludable-job-id"]
                    if not job_id and card.has_attr("data-job-id"):
                        job_id = card["data-job-id"]
                        
                    if not job_id:
                        continue
                        
                    title_elem = card.select_one(".job-card-list__title, .job-card-container__link, a.job-card-list__title")
                    title = title_elem.get_text().strip() if title_elem else ""
                    if not title and link_elem:
                        title = link_elem.get_text().strip()
                        
                    company_elem = card.select_one(".job-card-container__company-name, .job-card-container__primary-description, .artdeco-entity-lockup__subtitle")
                    company = company_elem.get_text().strip() if company_elem else ""
                    company = company.split("\n")[0].strip()
                    
                    loc_elem = card.select_one(".job-card-container__metadata-item, .job-card-container__primary-description")
                    loc_name = loc_elem.get_text().strip() if loc_elem else location
                    
                    job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                    
                    if not title or not company:
                        continue
                        
                    if any(x["job_id"] == job_id for x in parsed_jobs_info):
                        continue
                        
                    parsed_jobs_info.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "location_name": loc_name,
                        "job_url": job_url
                    })
                except Exception as card_err:
                    print(f"[LinkedIn] Error parsing card: {card_err}")
            
            print(f"[LinkedIn] Successfully parsed {len(parsed_jobs_info)} jobs. Fetching descriptions...")
            
            # Fetch descriptions using Playwright
            for info in parsed_jobs_info:
                try:
                    print(f"[LinkedIn] Fetching details for '{info['title']}' at {info['company']}...")
                    page.goto(info["job_url"], wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    
                    desc_elem = page.locator(".jobs-description__content, .jobs-description-content__text, div#job-details").first
                    about_job = ""
                    if desc_elem.is_visible():
                        about_job = desc_elem.inner_text().strip()
                    else:
                        info_soup = BeautifulSoup(page.content(), "lxml")
                        desc_div = info_soup.select_one(".jobs-description__content, .jobs-description-content__text, #job-details")
                        if desc_div:
                            about_job = desc_div.get_text(separator="\n").strip()
                            
                    if not about_job:
                        about_job = f"Job title: {info['title']}. Company: {info['company']}. Location: {info['location_name']}. Please apply directly on LinkedIn: {info['job_url']}"
                        
                    salary = None
                    salary_elem = page.locator(".job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight").first
                    if salary_elem.is_visible():
                        text = salary_elem.inner_text()
                        if "$" in text or "₹" in text or "£" in text or "€" in text:
                            salary = text.strip()
                    
                    job_obj = Job(
                        title=info["title"],
                        company=info["company"],
                        location=info["location_name"],
                        about_job=about_job,
                        site=["LinkedIn"],
                        url=info["job_url"],
                        salary=salary,
                        job_id=info["job_id"]
                    )
                    scraped_jobs.append(job_obj)
                    
                except Exception as desc_err:
                    print(f"[LinkedIn] Error fetching details for job ID {info['job_id']}: {desc_err}")
                    job_obj = Job(
                        title=info["title"],
                        company=info["company"],
                        location=info["location_name"],
                        about_job=f"Job title: {info['title']}. Company: {info['company']}. Location: {info['location_name']}. Link: {info['job_url']}",
                        site=["LinkedIn"],
                        url=info["job_url"],
                        job_id=info["job_id"]
                    )
                    scraped_jobs.append(job_obj)
            
            if browser:
                browser.close()
            else:
                context.close()
            
        print(f"[LinkedIn] Completed. Scraped {len(scraped_jobs)} jobs.")
        return scraped_jobs
