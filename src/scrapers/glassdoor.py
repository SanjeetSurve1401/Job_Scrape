from typing import Optional, List, Any
import os
import json
import re
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as fallback_requests

try:
    from jobspy import scrape_jobs
    HAS_JOBSPY = True
except ImportError:
    HAS_JOBSPY = False

from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job
from src.config import Config

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
        self.headers = {}
        self.cookies = {}
        self.live_fetch_disabled = False
        self.load_session()

    def load_session(self):
        """Loads session User-Agent and Cookie from .env via Config."""
        user_agent = Config.GLASSDOOR_USER_AGENT.strip()
        cookie_str = Config.GLASSDOOR_COOKIE.strip()

        if not user_agent or not cookie_str:
            if not HAS_JOBSPY:
                print("Warning: GLASSDOOR_USER_AGENT or GLASSDOOR_COOKIE not set in .env. Live Glassdoor requests will fail.")
            return

        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive"
        }

        # Parse Cookie header string into a dict for curl_cffi
        cookies_dict = {}
        for item in cookie_str.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                cookies_dict[k.strip()] = v.strip()
        self.cookies = cookies_dict

        print("Glassdoor session credentials loaded from .env successfully.")

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
        
        # Iterate values directly to locate pageProps (dynamic, avoids fragile hardcoded keys)
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
            # Clean RSC-specific tokens so we can parse as standard JSON
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

    # ── Extraction from HTML (local or live) ─────────────────────────

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
        
        # Resolve RSC references for each job
        resolved_jobs = []
        memo = {}
        for job_item in job_list:
            if isinstance(job_item, dict):
                resolved_jobs.append(self._resolve_rsc_references(job_item, state_map, memo))
        
        return resolved_jobs

    # ── Live Fetch (using curl_cffi) ─────────────────────────────────

    def fetch_live_search(self, keywords: str, location: str, page: int = 1) -> Optional[str]:
        """
        Fetches a Glassdoor search results page live using curl_cffi 
        with browser impersonation to bypass Cloudflare.
        """
        if self.live_fetch_disabled:
            return None
        
        if not HAS_CURL_CFFI:
            print("Warning: curl_cffi is not installed. Live Glassdoor fetching is disabled.")
            print("  Install it with: pip install curl_cffi")
            self.live_fetch_disabled = True
            return None
        
        if not self.cookies:
            print("Warning: No Glassdoor session cookies loaded. Live fetching is disabled.")
            self.live_fetch_disabled = True
            return None
        
        base_url = "https://www.glassdoor.com/Job/jobs.htm"
        params = {
            "sc.keyword": keywords,
            "locN": location,
            "p": page
        }
        
        try:
            response = cffi_requests.get(
                base_url,
                params=params,
                headers=self.headers,
                cookies=self.cookies,
                impersonate="firefox",
                timeout=15
            )
            
            if response.status_code == 403:
                print("Glassdoor returned 403 Forbidden. Session cookies may have expired or Cloudflare blocked the request.")
                print("  → To refresh cookies: Log into Glassdoor in your browser, copy the Cookie and User-Agent")
                print("    headers from DevTools (Network tab) into .env.")
                print("  → Skipping all further live Glassdoor requests for this run.")
                self.live_fetch_disabled = True
                return None
            elif response.status_code != 200:
                print(f"Glassdoor fetch failed with status code {response.status_code}")
                return None
            
            return response.text
            
        except Exception as e:
            print(f"Error fetching live Glassdoor search: {e}")
            self.live_fetch_disabled = True
            return None

    def _scrape_via_jobspy(self, role: str, location: str, limit: int) -> List[Job]:
        """Scrapes Glassdoor using the python-jobspy library."""
        print("[Glassdoor] Attempting scrape using python-jobspy...")
        try:
            df = scrape_jobs(
                site_name=["glassdoor"],
                search_term=role,
                location=location,
                results_wanted=limit
            )
            
            jobs = []
            records = df.to_dict(orient="records")
            for item in records:
                # Safely convert to string and handle potential NaN values (floats in pandas)
                title = str(item.get("title")).strip() if item.get("title") is not None else ""
                company = str(item.get("company")).strip() if item.get("company") is not None else ""
                loc = str(item.get("location")).strip() if item.get("location") is not None else ""
                url = str(item.get("job_url")).strip() if item.get("job_url") is not None else ""
                desc = str(item.get("description")).strip() if item.get("description") is not None else ""
                salary = item.get("salary")
                job_id = str(item.get("id") or "")
                
                # Check for pandas NaN values
                if title.lower() == "nan": title = ""
                if company.lower() == "nan": company = ""
                if loc.lower() == "nan": loc = ""
                if desc.lower() == "nan": desc = ""
                
                if not title or not company:
                    continue
                
                job_obj = Job(
                    title=title,
                    company=company,
                    location=loc if loc else location,
                    about_job=desc,
                    site=["Glassdoor"],
                    url=url,
                    salary=str(salary) if salary is not None and str(salary).lower() != "nan" else None,
                    job_id=job_id
                )
                jobs.append(job_obj)
            return jobs
        except Exception as e:
            print(f"[Glassdoor] python-jobspy execution failed: {e}. Falling back to manual scraping.")
            return []

    # ── Main Scrape Method ───────────────────────────────────────────

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> List[Job]:
        """Scrapes Glassdoor jobs from local HTML and/or live search."""
        print(f"Running Glassdoor Scraper for Role: '{role}', Location: '{location}'")
        
        all_raw_jobs = []
        
        # Strategy 1: Parse local HTML file if available (Fastest, zero network delay)
        if os.path.exists(self.search_html_path):
            print(f"Parsing local Glassdoor HTML file: {self.search_html_path}")
            with open(self.search_html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            local_jobs = self._extract_jobs_from_html(html_content)
            if local_jobs:
                print(f"Found {len(local_jobs)} job listings in local Glassdoor file.")
                all_raw_jobs.extend(local_jobs)
                
        # Strategy 2: If no local HTML file, try JobSpy (Highly reliable Cloudflare bypass)
        if not all_raw_jobs and HAS_JOBSPY:
            jobspy_jobs = self._scrape_via_jobspy(role, location, limit)
            if jobspy_jobs:
                return jobspy_jobs
        
        # Strategy 3: Fallback to live fetch via session credentials
        if not all_raw_jobs and HAS_CURL_CFFI and not self.live_fetch_disabled:
            print("No local results or JobSpy. Attempting live Glassdoor session search...")
            live_html = self.fetch_live_search(role, location)
            if live_html:
                live_jobs = self._extract_jobs_from_html(live_html)
                if live_jobs:
                    print(f"Found {len(live_jobs)} job listings from live Glassdoor search.")
                    all_raw_jobs.extend(live_jobs)
        
        if not all_raw_jobs:
            print("No Glassdoor job listings found from any source.")
            return []
        
        # Limit the listings
        all_raw_jobs = all_raw_jobs[:limit]
        
        # Convert raw job data to Job objects
        scraped_jobs = []
        for item in all_raw_jobs:
            jobview = item.get("jobview", {})
            header = jobview.get("header", {})
            job_details = jobview.get("job", {})
            
            title = header.get("jobTitleText") or job_details.get("jobTitleText") or ""
            
            company = header.get("employerNameFromSearch") or ""
            if not company and "employer" in header:
                company = header["employer"].get("name") or header["employer"].get("shortName") or ""
            
            location_name = header.get("locationName", "")
            
            # Construct URL
            url = header.get("seoJobLink") or ""
            if url and not url.startswith("http"):
                url = "https://www.glassdoor.co.in" + url
            
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
            
            # Extract description from the payload (no live fetch needed)
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
            
        return scraped_jobs
