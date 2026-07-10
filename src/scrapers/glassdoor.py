import os
import time
import re
import json
import urllib.parse
from typing import Optional, List, Any
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job

@register_scraper
class GlassdoorScraper(BaseScraper):
    # Precompile regular expressions at class level
    _PUSH_PATTERN = re.compile(r'self\.__next_f\.push\(\[\d+,\s*"(.*?)"\]\)', re.DOTALL)
    _CHUNK_PATTERN = re.compile(r'^([a-zA-Z0-9]+):(.*)')
    _L_REF_PATTERN = re.compile(r'"\$L[a-zA-Z0-9]+"')
    _UNDEF_PATTERN = re.compile(r'\$undefined')
    _JL_PATTERN = re.compile(r'jl=(\d+)')

    def __init__(self):
        self.search_html_path = "glassdoor_search.html"

    # ── RSC Parsing Helpers ──────────────────────────────────────────

    def _build_rsc_state_map(self, html_content: str) -> dict:
        """
        Parses Next.js App Router React Server Components (RSC) stream
        chunks from <script> tags containing self.__next_f.push calls
        and builds a state map of chunk_id -> chunk_data.
        """
        state_map = {}
        soup = BeautifulSoup(html_content, "html.parser")
        scripts = soup.find_all("script")
        
        for s in scripts:
            if s.string and "self.__next_f.push" in s.string:
                matches = self._PUSH_PATTERN.findall(s.string)
                for m in matches:
                    try:
                        decoded = m.encode().decode('unicode_escape')
                    except Exception:
                        decoded = m
                    
                    lines = decoded.split("\n")
                    for line in lines:
                        match = self._CHUNK_PATTERN.match(line)
                        if match:
                            chunk_id = match.group(1)
                            chunk_data = match.group(2)
                            state_map[chunk_id] = chunk_data
        return state_map

    def _find_page_props(self, state_map: dict) -> Optional[dict]:
        """Locates the pageProps JSON payload from the RSC state map."""
        page_props_str = ""
        
        # Iterate values directly to locate pageProps
        for val in state_map.values():
            if "pageProps" in val:
                page_props_str = val
                break
        
        if not page_props_str:
            return None
        
        start_brace = page_props_str.find('{')
        end_brace = page_props_str.rfind('}')
        if start_brace == -1 or end_brace == -1:
            return None
        
        json_str = page_props_str[start_brace:end_brace + 1]
        try:
            cleaned = self._L_REF_PATTERN.sub('null', json_str)
            cleaned = self._UNDEF_PATTERN.sub('null', cleaned)
            return json.loads(cleaned)
        except Exception as e:
            print(f"Error parsing pageProps JSON: {e}")
            return None

    def _find_key_recursive(self, data: Any, target_key: str, max_depth: int = 50, current_depth: int = 0) -> Any:
        """Recursively scans nested JSON for a target key with cycle/depth protection."""
        if current_depth > max_depth:
            return None

        if isinstance(data, dict):
            if target_key in data:
                return data[target_key]
            for v in data.values():
                res = self._find_key_recursive(v, target_key, max_depth, current_depth + 1)
                if res is not None:
                    return res
        elif isinstance(data, list):
            for item in data:
                res = self._find_key_recursive(item, target_key, max_depth, current_depth + 1)
                if res is not None:
                    return res
        return None

    def _resolve_rsc_references(self, data: Any, state_map: dict, memo: Optional[dict] = None) -> Any:
        """Recursively resolves Next.js RSC $xx references from the state_map with memoization."""
        if memo is None:
            memo = {}

        if isinstance(data, dict):
            return {k: self._resolve_rsc_references(v, state_map, memo) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._resolve_rsc_references(item, state_map, memo) for item in data]
        elif isinstance(data, str):
            if data.startswith("$") and len(data) > 1:
                ref_key = data[1:]
                if ref_key in memo:
                    return memo[ref_key]
                if ref_key in state_map:
                    ref_val = state_map[ref_key]
                    try:
                        cleaned = self._L_REF_PATTERN.sub('null', ref_val)
                        cleaned = self._UNDEF_PATTERN.sub('null', cleaned)
                        parsed_val = json.loads(cleaned)
                        resolved = self._resolve_rsc_references(parsed_val, state_map, memo)
                        memo[ref_key] = resolved
                        return resolved
                    except Exception:
                        memo[ref_key] = ref_val
                        return ref_val
            return data
        return data

    def _extract_jobs_from_html(self, html_content: str) -> list:
        """
        Extracts job listing data from a Glassdoor HTML page by parsing 
        the Next.js RSC state map and resolving references.
        Returns a list of raw job dicts from the jobListings array.
        """
        state_map = self._build_rsc_state_map(html_content)
        if not state_map:
            print("Failed to parse Next.js RSC state from Glassdoor HTML.")
            return []
        
        page_data = self._find_page_props(state_map)
        if not page_data:
            print("Could not locate pageProps in Glassdoor RSC state.")
            return []
        
        job_listings_container = self._find_key_recursive(page_data, "jobListings")
        if not job_listings_container:
            print("Could not find jobListings in page state.")
            return []
        
        job_list = []
        if isinstance(job_listings_container, dict) and "jobListings" in job_listings_container:
            job_list = job_listings_container["jobListings"]
        elif isinstance(job_listings_container, list):
            job_list = job_listings_container
        
        resolved_jobs = []
        memo = {}
        for job_item in job_list:
            if isinstance(job_item, dict):
                resolved_jobs.append(self._resolve_rsc_references(job_item, state_map, memo))
        
        return resolved_jobs

    # ── Main Scrape Method ───────────────────────────────────────────

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> List[Job]:
        print(f"\n[Glassdoor] Starting Playwright Scraper for Role: '{role}', Location: '{location}' (Limit: {limit})")
        scraped_jobs = []
        user_data_dir = os.path.abspath("./playwright_glassdoor_session")
        
        if not os.path.exists(user_data_dir):
            print("[Glassdoor ERROR] Persistent session directory does not exist! Run glassdoor_login.py first.")
            return []
            
        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=True,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"]
                )
            except Exception as e:
                print(f"[Glassdoor] Failed to launch with Chrome channel ({e}). Trying default chromium...")
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--enable-automation"]
                    )
                except Exception as e2:
                    print(f"[Glassdoor ERROR] Could not launch Playwright browser context: {e2}")
                    return []
            
            page = context.pages[0] if context.pages else context.new_page()
            
            query_role = urllib.parse.quote(role)
            query_loc = urllib.parse.quote(location)
            url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query_role}&locN={query_loc}"
            
            print(f"[Glassdoor] Navigating to: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                # Check for login redirection
                if "member/profile" in page.url:
                    print("[Glassdoor ERROR] Session expired or not logged in! Run glassdoor_login.py to update session.")
                    context.close()
                    return []
                
                page.wait_for_selector("[data-test='job-listing-item'], ul", timeout=15000)
            except Exception as e:
                print(f"[Glassdoor] Warning: selector not found or timeout: {e}")

            html_content = page.content()
            context.close()

        # Parse local HTML file fallback or the dynamic page HTML
        all_raw_jobs = self._extract_jobs_from_html(html_content)
        if not all_raw_jobs:
            print("[Glassdoor] No jobs parsed from live HTML page. Falling back to local search HTML file...")
            if os.path.exists(self.search_html_path):
                with open(self.search_html_path, 'r', encoding='utf-8') as f:
                    local_html = f.read()
                all_raw_jobs = self._extract_jobs_from_html(local_html)
                
        if not all_raw_jobs:
            print("[Glassdoor] No job listings found.")
            return []
            
        all_raw_jobs = all_raw_jobs[:limit]
        
        # Convert raw job data to Job objects
        for item in all_raw_jobs:
            try:
                jobview = item.get("jobview", {})
                header = jobview.get("header", {})
                job_details = jobview.get("job", {})
                
                title = header.get("jobTitleText") or job_details.get("jobTitleText") or ""
                
                company = header.get("employerNameFromSearch") or ""
                if not company and "employer" in header:
                    company = header["employer"].get("name") or header["employer"].get("shortName") or ""
                
                location_name = header.get("locationName", "")
                
                url = header.get("seoJobLink") or ""
                if url and not url.startswith("http"):
                    url = "https://www.glassdoor.com" + url
                
                # Handle salary
                salary_info = header.get("payPeriodAdjustedPay")
                salary = None
                if salary_info:
                    p10 = salary_info.get("p10")
                    p90 = salary_info.get("p90")
                    p50 = salary_info.get("p50")
                    currency = header.get("payCurrency", "INR")
                    if p10 and p90:
                        salary = f"{currency} {p10} - {p90}"
                    elif p50:
                        salary = f"{currency} {p50}"
                
                desc_fragments = job_details.get("descriptionFragmentsText")
                about_job = ""
                if isinstance(desc_fragments, list):
                    about_job = " ".join([str(f) for f in desc_fragments if f])
                elif isinstance(desc_fragments, str):
                    about_job = desc_fragments
                
                if not about_job:
                    about_job = f"Job title: {title}. Company: {company}. Location: {location_name}. For full description and to apply, please view: {url}"
                
                job_id = str(job_details.get("listingId") or "")
                if not job_id:
                    jl_match = self._JL_PATTERN.search(url) if url else None
                    if jl_match:
                        job_id = jl_match.group(1)
                
                job_obj = Job(
                    title=title,
                    company=company,
                    location=location_name,
                    about_job=about_job,
                    site=["Glassdoor"],
                    url=url,
                    salary=salary,
                    job_id=job_id
                )
                scraped_jobs.append(job_obj)
            except Exception as e:
                print(f"[Glassdoor] Error processing listing: {e}")
                
        return scraped_jobs
