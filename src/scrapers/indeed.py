import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as cffi_requests

try:
    from jobspy import scrape_jobs
    HAS_JOBSPY = True
except ImportError:
    HAS_JOBSPY = False

from src.scrapers.base import BaseScraper
from src.scrapers import register_scraper
from src.models import Job

@register_scraper
class IndeedScraper(BaseScraper):
    _JK_PATTERN = re.compile(r'jk=([a-f0-9]+)')
    _BEACON_PATTERN = re.compile("job_seen_beacon")
    _TITLE_PATTERN = re.compile("jobTitle")
    _H_PATTERN = re.compile("h[23]")
    _SALARY_PATTERN = re.compile("salary-snippet")
    _META_PATTERN = re.compile("metadata")
    _NEW_CLEAN_PATTERN = re.compile(r'^new\s+', re.IGNORECASE)

    # Configurable Indian keywords to select in.indeed.com domain
    INDIAN_REGIONS = {"india", "pune", "mumbai", "bangalore", "bengaluru", "delhi", "noida", "gurgaon", "hyderabad", "chennai"}

    def __init__(self):
        # We will use cffi_requests.Session if HAS_CURL_CFFI is True
        self.session = cffi_requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
            "DNT": "1"
        }
        self.session.headers.update(self.headers)

    def fetch_job_description(self, jk: str, base_url: str) -> str:
        """Fetches the job details page for a specific Indeed job key."""
        if not jk:
            return ""
            
        url = f"{base_url}/viewjob?jk={jk}"
        try:
            if HAS_CURL_CFFI:
                response = self.session.get(url, impersonate="firefox", timeout=15)
            else:
                response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Check for description container on Indeed
                desc_div = soup.find("div", id="jobDescriptionText")
                if desc_div:
                    return desc_div.get_text(separator="\n").strip()
                
                # Alternate selectors
                desc_content = soup.find("div", class_="jobsearch-jobDescriptionText")
                if desc_content:
                    return desc_content.get_text(separator="\n").strip()
                    
                return soup.get_text(separator="\n").strip()
        except Exception as e:
            print(f"Error fetching Indeed job description for jk {jk}: {e}")
            
        return ""

    def _scrape_via_jobspy(self, role: str, location: str, limit: int) -> List[Job]:
        """Scrapes Indeed using the python-jobspy library."""
        print("[Indeed] Attempting scrape using python-jobspy...")
        loc_lower = location.lower()
        country = "India" if any(region in loc_lower for region in self.INDIAN_REGIONS) else None
        
        try:
            df = scrape_jobs(
                site_name=["indeed"],
                search_term=role,
                location=location,
                results_wanted=limit,
                country_indeed=country
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
                
                # Extract experience range if available
                exp_req = item.get("experience_range")
                if exp_req is not None:
                    exp_req = str(exp_req).strip()
                    if exp_req.lower() == "nan":
                        exp_req = None
                
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
                    site=["Indeed"],
                    url=url,
                    salary=str(salary) if salary is not None and str(salary).lower() != "nan" else None,
                    experience_required=exp_req,
                    job_id=job_id
                )
                jobs.append(job_obj)
            return jobs
        except Exception as e:
            print(f"[Indeed] python-jobspy execution failed: {e}. Falling back to manual scraping.")
            return []

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> List[Job]:
        """Scrapes Indeed jobs matching the role and location."""
        print(f"Running Indeed Scraper for Role: '{role}', Location: '{location}'")
        
        if HAS_JOBSPY:
            jobs = self._scrape_via_jobspy(role, location, limit)
            if jobs:
                return jobs

        # Fallback to manual scraping if JobSpy is not installed or failed
        import urllib.parse
        query_role = urllib.parse.quote(role)
        query_location = urllib.parse.quote(location)
        
        loc_lower = location.lower()
        is_india_region = any(region in loc_lower for region in self.INDIAN_REGIONS)
        base_url = "https://in.indeed.com" if is_india_region else "https://www.indeed.com"
        url = f"{base_url}/jobs?q={query_role}&l={query_location}"
        
        scraped_jobs = []
        try:
            if HAS_CURL_CFFI:
                response = self.session.get(url, impersonate="firefox", timeout=15)
            else:
                response = self.session.get(url, timeout=15)
            
            if response.status_code == 403 or response.status_code == 503:
                print("Indeed returned 403/503. The request was blocked by Cloudflare anti-bot system. Skipping Indeed live search.")
                return []
                
            if response.status_code != 200:
                print(f"Indeed search returned status code: {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Indeed job card links or containers typically have class job_seen_beacon or contain data-jk
            job_cards = soup.find_all("div", class_=self._BEACON_PATTERN)
            if not job_cards:
                # Alternate selectors
                job_cards = soup.find_all("td", class_="resultContent")
                
            print(f"Found {len(job_cards)} job cards in Indeed search response.")
            
            # Limit the job cards processed
            job_cards = job_cards[:limit]
            
            # Phase 1: Parse basic card data synchronously
            parsed_cards = []
            for card in job_cards:
                # Find the job title link which contains data-jk or href
                a_link = card.find("a", href=True)
                if not a_link:
                    continue
                    
                href = a_link["href"]
                # Extract jk (job key)
                jk_match = self._JK_PATTERN.search(href)
                jk = jk_match.group(1) if jk_match else ""
                
                if not jk:
                    # Try getting from parent tags
                    parent = card.find_parent(attrs={"data-jk": True})
                    if parent:
                        jk = parent["data-jk"]
                        
                if not jk:
                    continue
                    
                # Title
                title_elem = card.find("h2", class_=self._TITLE_PATTERN)
                if not title_elem:
                    title_elem = card.find(self._H_PATTERN)
                title = title_elem.get_text().strip() if title_elem else ""
                # Indeed sometimes adds "new" text inside the title element, clean it up
                title = self._NEW_CLEAN_PATTERN.sub('', title)
                
                # Company
                company_elem = card.find("span", attrs={"data-testid": "company-name"})
                if not company_elem:
                    company_elem = card.find("span", class_="companyName")
                company = company_elem.get_text().strip() if company_elem else ""
                
                # Location
                location_elem = card.find("div", attrs={"data-testid": "text-location"})
                if not location_elem:
                    location_elem = card.find("div", class_="companyLocation")
                location_name = location_elem.get_text().strip() if location_elem else ""
                
                # Salary
                salary_elem = card.find("div", class_=self._SALARY_PATTERN)
                if not salary_elem:
                    salary_elem = card.find("div", class_=self._META_PATTERN)
                salary = salary_elem.get_text().strip() if salary_elem else None
                
                if not title or not company:
                    continue
                
                parsed_cards.append({
                    "jk": jk,
                    "title": title,
                    "company": company,
                    "location_name": location_name,
                    "salary": salary,
                    "job_url": f"{base_url}/viewjob?jk={jk}"
                })

            # Phase 2: Fetch job descriptions in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self.fetch_job_description, c["jk"], base_url): c 
                    for c in parsed_cards
                }
                
                for future in futures:
                    c = futures[future]
                    try:
                        about_job = future.result()
                    except Exception as exc:
                        print(f"Error resolving future for Indeed job jk {c['jk']}: {exc}")
                        about_job = ""
                        
                    if not about_job:
                        about_job = f"Job title: {c['title']}. Company: {c['company']}. Location: {c['location_name']}. For full description and to apply, please view: {c['job_url']}"
                        
                    job_obj = Job(
                        title=c["title"],
                        company=c["company"],
                        location=c["location_name"],
                        about_job=about_job,
                        site=["Indeed"],
                        url=c["job_url"],
                        salary=c["salary"],
                        job_id=c["jk"]
                    )
                    scraped_jobs.append(job_obj)
                
        except Exception as e:
            print(f"Error scraping Indeed: {e}")
            
        return scraped_jobs
