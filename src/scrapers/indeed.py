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
class IndeedScraper(BaseScraper):
    INDIAN_REGIONS = {"india", "pune", "mumbai", "bangalore", "bengaluru", "delhi", "noida", "gurgaon", "hyderabad", "chennai"}

    def scrape(self, role: str, location: str, experience: str, limit: int = 10, start_offset: int = 0) -> List[Job]:
        print(f"\n[Indeed] Starting Playwright Scraper for Role: '{role}', Location: '{location}' (Limit: {limit}, Offset: {start_offset})")
        scraped_jobs = []
        
        # Load storage state from Config
        storage_state = None
        if Config.INDEED_STORAGE_STATE and Config.INDEED_STORAGE_STATE.strip():
            try:
                storage_state = json.loads(Config.INDEED_STORAGE_STATE)
                print("[Indeed] Loaded storage state from .env settings.")
            except Exception as e:
                print(f"[Indeed Warning] Failed to parse INDEED_STORAGE_STATE JSON: {e}")

        # Determine domain (Indeed India vs Global)
        loc_lower = location.lower()
        base_url = "https://in.indeed.com" if any(region in loc_lower for region in self.INDIAN_REGIONS) else "https://www.indeed.com"
        
        user_data_dir = os.path.abspath("./playwright_indeed_session")
        
        with sync_playwright() as p:
            browser = None
            context = None
            
            try:
                if storage_state:
                    # Use storage state in a clean browser session
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=storage_state,
                        user_agent=Config.INDEED_USER_AGENT
                    )
                else:
                    # Fallback to persistent context folder
                    if not os.path.exists(user_data_dir):
                        print("[Indeed ERROR] No storage state in .env or session directory found! Run indeed_login.py first.")
                        return []
                    print("[Indeed] Using persistent session directory.")
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=True,
                        channel="chrome",
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--enable-automation"]
                    )
            except Exception as e:
                print(f"[Indeed ERROR] Could not launch Playwright browser context: {e}")
                return []
            
            page = context.pages[0] if context.pages else context.new_page()
            
            query_role = urllib.parse.quote(role)
            query_loc = urllib.parse.quote(location)
            url = f"{base_url}/jobs?q={query_role}&l={query_loc}"
            if start_offset > 0:
                url += f"&start={start_offset}"
            
            print(f"[Indeed] Navigating to: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                # Check for login redirection
                if "signin" in page.url:
                    print("[Indeed ERROR] Session expired or not logged in! Run indeed_login.py to update session.")
                    if browser:
                        browser.close()
                    else:
                        context.close()
                    return []
                
                # Wait for job list elements
                page.wait_for_selector(".job_seen_beacon, td.resultContent, #mosaic-provider-jobcards", timeout=15000)
            except Exception as e:
                print(f"[Indeed] Warning: job list selector not found or timeout: {e}")

            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Select job items
            cards = soup.select(".job_seen_beacon, td.resultContent")
            print(f"[Indeed] Found {len(cards)} raw job cards in HTML.")
            
            parsed_jobs_info = []
            for card in cards:
                if len(parsed_jobs_info) >= limit:
                    break
                    
                try:
                    title_elem = card.select_one("h2.jobTitle, a.jcs-JobTitle")
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text().strip()
                    
                    jk = ""
                    link_elem = card.select_one("a.jcs-JobTitle, a[data-jk]")
                    if link_elem and link_elem.has_attr("data-jk"):
                        jk = link_elem["data-jk"]
                    if not jk and link_elem and link_elem.has_attr("href"):
                        match = re.search(r"jk=([a-f0-9]+)", link_elem["href"])
                        if match:
                            jk = match.group(1)
                            
                    if not jk:
                        outer_a = card.find_parent("a", href=True)
                        if outer_a:
                            match = re.search(r"jk=([a-f0-9]+)", outer_a["href"])
                            if match:
                                jk = match.group(1)
                                
                    if not jk:
                        continue
                        
                    company_elem = card.select_one("[data-testid='company-name'], .companyName, .company_name")
                    company = company_elem.get_text().strip() if company_elem else ""
                    
                    loc_elem = card.select_one("[data-testid='text-location'], .companyLocation, .location")
                    loc_name = loc_elem.get_text().strip() if loc_elem else location
                    
                    job_url = f"{base_url}/viewjob?jk={jk}"
                    
                    if not title or not company:
                        continue
                        
                    if any(x["jk"] == jk for x in parsed_jobs_info):
                        continue
                        
                    salary = None
                    salary_elem = card.select_one(".salary-snippet-container, .metadata.salary-snippet-container, .salary-snippet")
                    if salary_elem:
                        salary = salary_elem.get_text().strip()
                    
                    parsed_jobs_info.append({
                        "jk": jk,
                        "title": title,
                        "company": company,
                        "location_name": loc_name,
                        "job_url": job_url,
                        "salary": salary
                    })
                except Exception as card_err:
                    print(f"[Indeed] Error parsing card: {card_err}")
                    
            print(f"[Indeed] Successfully parsed {len(parsed_jobs_info)} jobs. Fetching descriptions...")
            
            # Fetch descriptions using Playwright
            for info in parsed_jobs_info:
                try:
                    print(f"[Indeed] Fetching details for '{info['title']}' at {info['company']}...")
                    page.goto(info["job_url"], wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    
                    desc_elem = page.locator("#jobDescriptionText, .jobsearch-jobDescriptionText").first
                    about_job = ""
                    if desc_elem.is_visible():
                        about_job = desc_elem.inner_text().strip()
                    else:
                        info_soup = BeautifulSoup(page.content(), "lxml")
                        desc_div = info_soup.select_one("#jobDescriptionText, .jobsearch-jobDescriptionText")
                        if desc_div:
                            about_job = desc_div.get_text(separator="\n").strip()
                            
                    if not about_job:
                        about_job = f"Job title: {info['title']}. Company: {info['company']}. Location: {info['location_name']}. Please apply directly on Indeed: {info['job_url']}"
                        
                    job_obj = Job(
                        title=info["title"],
                        company=info["company"],
                        location=info["location_name"],
                        about_job=about_job,
                        site=["Indeed"],
                        url=info["job_url"],
                        salary=info["salary"],
                        job_id=info["jk"]
                    )
                    scraped_jobs.append(job_obj)
                    
                except Exception as desc_err:
                    print(f"[Indeed] Error fetching details for job ID {info['jk']}: {desc_err}")
                    job_obj = Job(
                        title=info["title"],
                        company=info["company"],
                        location=info["location_name"],
                        about_job=f"Job title: {info['title']}. Company: {info['company']}. Location: {info['location_name']}. Link: {info['job_url']}",
                        site=["Indeed"],
                        url=info["job_url"],
                        salary=info["salary"],
                        job_id=info["jk"]
                    )
                    scraped_jobs.append(job_obj)
            
            if browser:
                browser.close()
            else:
                context.close()
            
        print(f"[Indeed] Completed. Scraped {len(scraped_jobs)} jobs.")
        return scraped_jobs
