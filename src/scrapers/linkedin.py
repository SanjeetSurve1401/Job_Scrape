import os
import time
import re
import json
import urllib.parse
import urllib.request
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from src.config import Config
from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job

@register_scraper
class LinkedInScraper(BaseScraper):
    # Time windows in seconds requested by user:
    # 2h (7200s), 6h (21600s), 12h (43200s), 18h (64800s), 24h (86400s)
    TIME_WINDOWS = [
        ("Last 2 Hours", 7200),
        ("Last 6 Hours", 21600),
        ("Last 12 Hours", 43200),
        ("Last 18 Hours", 64800),
        ("Last 24 Hours", 86400),
        ("All-Time", None)
    ]

    def _fetch_guest_jobs(self, role: str, location: str, seconds: int = None, start: int = 0) -> List[Dict[str, str]]:
        """Fallback to LinkedIn search endpoint to ensure jobs are always found even if UI redirects."""
        query_role = urllib.parse.quote(role)
        query_loc = urllib.parse.quote(location)
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query_role}&location={query_loc}&start={start}"
        if seconds:
            url += f"&f_TPR=r{seconds}"
            
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': Config.LINKEDIN_USER_AGENT or 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'lxml')
                cards = soup.select('li')
                results = []
                for c in cards:
                    title_elem = c.select_one('.base-search-card__title')
                    comp_elem = c.select_one('.base-search-card__subtitle')
                    link_elem = c.find('a', href=True)
                    loc_elem = c.select_one('.job-search-card__location')
                    if title_elem and comp_elem and link_elem:
                        href = link_elem['href']
                        m = re.search(r'/jobs/view/[^?]*?(\d+)', href) or re.search(r'/jobs/view/(\d+)', href)
                        job_id = m.group(1) if m else ""
                        clean_url = href.split('?')[0] if '?' in href else href
                        results.append({
                            'job_id': job_id,
                            'title': title_elem.get_text(strip=True),
                            'company': comp_elem.get_text(strip=True),
                            'location_name': loc_elem.get_text(strip=True) if loc_elem else location,
                            'job_url': clean_url
                        })
                return results
        except Exception as e:
            return []

    def _fetch_guest_description(self, job_id: str) -> str:
        """Fetches job description cleanly via guest endpoint if Playwright page hangs."""
        if not job_id:
            return ""
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': Config.LINKEDIN_USER_AGENT or 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'lxml')
                desc = soup.select_one('.show-more-less-html__markup, .jobs-description__content, div#job-details')
                if desc:
                    return desc.get_text(separator="\n").strip()
        except Exception:
            pass
        return ""

    def scrape(self, role: str, location: str, experience: str, limit: int = 10, start_offset: int = 0) -> List[Job]:
        print(f"\n[LinkedIn] Starting Playwright Scraper for Role: '{role}', Location: '{location}' (Limit: {limit}, Offset: {start_offset})")
        scraped_jobs: List[Job] = []
        seen_job_ids = set()
        seen_title_comp = set()
        
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
                pass
                
        user_data_dir = os.path.abspath("./playwright_linkedin_session")
        
        with sync_playwright() as p:
            browser = None
            context = None
            
            try:
                if storage_state:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=storage_state,
                        user_agent=Config.LINKEDIN_USER_AGENT,
                        viewport={'width': 1280, 'height': 800}
                    )
                else:
                    if os.path.exists(user_data_dir):
                        context = p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            headless=True,
                            channel="chrome",
                            args=["--disable-blink-features=AutomationControlled"],
                            ignore_default_args=["--enable-automation"],
                            viewport={'width': 1280, 'height': 800}
                        )
                    else:
                        browser = p.chromium.launch(headless=True)
                        context = browser.new_context(
                            user_agent=Config.LINKEDIN_USER_AGENT,
                            viewport={'width': 1280, 'height': 800}
                        )
            except Exception as e:
                print(f"[LinkedIn ERROR] Could not launch browser session: {e}")
            
            page = context.pages[0] if context and context.pages else (context.new_page() if context else None)
            
            query_role = urllib.parse.quote(role)
            query_loc = urllib.parse.quote(location)
            
            # Iterate through time windows (2h -> 6h -> 12h -> 18h -> 24h -> all-time)
            for window_name, seconds in self.TIME_WINDOWS:
                if len(scraped_jobs) >= limit:
                    break
                    
                time_filter_str = f"&f_TPR=r{seconds}" if seconds else ""
                url = f"https://www.linkedin.com/jobs/search/?keywords={query_role}&location={query_loc}{time_filter_str}"
                if start_offset > 0:
                    url += f"&start={start_offset}"
                    
                print(f"[LinkedIn] Checking time window: {window_name} -> {url}")
                parsed_window_jobs = []
                
                # 1. Try Playwright extraction
                if page:
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3000)
                        
                        # Scroll to trigger lazy loading
                        try:
                            pane_selector = ".jobs-search-results-list, .jobs-search-results-list__container, .scaffold-layout__list-container"
                            pane = page.locator(pane_selector).first
                            if pane.count() > 0:
                                for _ in range(3):
                                    pane.evaluate("el => el.scrollTop = el.scrollHeight")
                                    page.wait_for_timeout(800)
                        except Exception:
                            pass
                            
                        html = page.content()
                        soup = BeautifulSoup(html, "lxml")
                        
                        # Match classic and modern card selectors
                        cards = soup.select("li.jobs-search-results__list-item, div.job-card-container, [data-occludable-job-id], [data-job-id], li.base-search-card")
                        for card in cards:
                            link_elem = card.find("a", href=True)
                            if not link_elem:
                                continue
                            href = link_elem["href"]
                            job_id = ""
                            m = re.search(r"/jobs/view/(\d+)", href) or re.search(r"currentJobId=(\d+)", href)
                            if m:
                                job_id = m.group(1)
                            if not job_id and card.has_attr("data-occludable-job-id"):
                                job_id = card["data-occludable-job-id"]
                            if not job_id and card.has_attr("data-job-id"):
                                job_id = card["data-job-id"]
                            if not job_id:
                                continue
                                
                            title_elem = card.select_one(".job-card-list__title, .job-card-container__link, a.job-card-list__title, .base-search-card__title")
                            title = title_elem.get_text().strip() if title_elem else link_elem.get_text().strip()
                            title = " ".join(title.split("\n")[0].split())
                            
                            company_elem = card.select_one(".job-card-container__company-name, .job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .base-search-card__subtitle")
                            company = company_elem.get_text().strip() if company_elem else ""
                            company = " ".join(company.split("\n")[0].split())
                            
                            loc_elem = card.select_one(".job-card-container__metadata-item, .job-card-container__primary-description, .job-search-card__location")
                            loc_name = loc_elem.get_text().strip() if loc_elem else location
                            loc_name = " ".join(loc_name.split())
                            
                            if title and company:
                                clean_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                                parsed_window_jobs.append({
                                    "job_id": job_id,
                                    "title": title,
                                    "company": company,
                                    "location_name": loc_name,
                                    "job_url": clean_url
                                })
                    except Exception as pw_err:
                        pass
                
                # 2. If Playwright found 0 cards (due to redirect or layout change), use fallback endpoint
                if not parsed_window_jobs:
                    fallback_jobs = self._fetch_guest_jobs(role, location, seconds=seconds, start=start_offset)
                    parsed_window_jobs.extend(fallback_jobs)
                
                print(f"[LinkedIn] Found {len(parsed_window_jobs)} raw job cards in {window_name}.")
                
                # Process descriptions and build Job models
                for info in parsed_window_jobs:
                    if len(scraped_jobs) >= limit:
                        break
                    
                    jid = info["job_id"]
                    t_c_key = f"{info['title'].lower()}|{info['company'].lower()}"
                    if (jid and jid in seen_job_ids) or (t_c_key in seen_title_comp):
                        continue
                        
                    seen_job_ids.add(jid)
                    seen_title_comp.add(t_c_key)
                    
                    about_job = ""
                    # Try Playwright description fetch
                    if page:
                        try:
                            page.goto(info["job_url"], wait_until="domcontentloaded", timeout=25000)
                            page.wait_for_timeout(2000)
                            desc_elem = page.locator(".jobs-description__content, .jobs-description-content__text, div#job-details").first
                            if desc_elem.is_visible():
                                about_job = desc_elem.inner_text().strip()
                        except Exception:
                            pass
                            
                    # Fallback description fetch if empty
                    if not about_job:
                        about_job = self._fetch_guest_description(jid)
                        
                    if not about_job:
                        about_job = f"Job title: {info['title']}. Company: {info['company']}. Location: {info['location_name']}. Link: {info['job_url']}"
                        
                    job_obj = Job(
                        title=info["title"],
                        company=info["company"],
                        location=info["location_name"],
                        about_job=about_job,
                        site=["LinkedIn"],
                        url=info["job_url"],
                        job_id=jid
                    )
                    scraped_jobs.append(job_obj)
            
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            elif context:
                try:
                    context.close()
                except Exception:
                    pass
                    
        print(f"[LinkedIn] Completed. Scraped {len(scraped_jobs)} jobs.")
        return scraped_jobs
