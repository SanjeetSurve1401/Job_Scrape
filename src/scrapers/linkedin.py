import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from typing import List

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
class LinkedInScraper(BaseScraper):
    _BASE_CARD_PATTERN = re.compile("base-card")
    _FULL_LINK_PATTERN = re.compile("base-card__full-link")
    _TITLE_PATTERN = re.compile("base-search-card__title")
    _SUBTITLE_PATTERN = re.compile("base-search-card__subtitle")
    _LOCATION_PATTERN = re.compile("job-search-card__location")

    def __init__(self):
        self.session = requests.Session()
        user_agent = getattr(Config, "LINKEDIN_USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.session.headers.update(self.headers)
        
        cookie = getattr(Config, "LINKEDIN_COOKIE", None)
        if cookie:
            self.session.headers.update({"Cookie": cookie})

    def fetch_job_description(self, job_id: str) -> str:
        """Fetches the detailed job description HTML page and extracts text."""
        if not job_id:
            return ""
            
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobCardContent/{job_id}"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                desc_section = soup.find("div", class_="show-more-less-html__markup")
                if not desc_section:
                    desc_section = soup.find("section", class_="description")
                if not desc_section:
                    desc_section = soup
                    
                return desc_section.get_text(separator="\n").strip()
            else:
                url_view = f"https://www.linkedin.com/jobs/view/{job_id}"
                response_view = self.session.get(url_view, timeout=10)
                if response_view.status_code == 200:
                    soup = BeautifulSoup(response_view.text, 'lxml')
                    desc_div = soup.find("div", class_="description__text")
                    if not desc_div:
                        desc_div = soup.find("div", class_=re.compile("show-more-less-html__markup"))
                    if desc_div:
                        return desc_div.get_text(separator="\n").strip()
        except Exception as e:
            print(f"Error fetching LinkedIn job description for ID {job_id}: {e}")
            
        return ""

    def _scrape_via_jobspy(self, role: str, location: str, limit: int) -> List[Job]:
        """Scrapes LinkedIn using the python-jobspy library."""
        print("[LinkedIn] Attempting scrape using python-jobspy...")
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
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
                    site=["LinkedIn"],
                    url=url,
                    salary=str(salary) if salary is not None and str(salary).lower() != "nan" else None,
                    job_id=job_id
                )
                jobs.append(job_obj)
            return jobs
        except Exception as e:
            print(f"[LinkedIn] python-jobspy execution failed: {e}. Falling back to manual scraping.")
            return []

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> List[Job]:
        """Scrapes LinkedIn jobs matching the search query parameters."""
        print(f"Running LinkedIn Scraper for Role: '{role}', Location: '{location}'")
        
        # If we do not have cookies, try jobspy first. If we have cookies, use manual scraper with session cookies.
        use_jobspy = HAS_JOBSPY and not getattr(Config, "LINKEDIN_COOKIE", None)
        if use_jobspy:
            jobs = self._scrape_via_jobspy(role, location, limit)
            if jobs:
                return jobs

        # Fallback to manual guest scraping
        query_role = requests.utils.quote(role)
        query_location = requests.utils.quote(location)
        
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query_role}&location={query_location}&start=0"
        
        scraped_jobs = []
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                print(f"LinkedIn search returned status code: {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'lxml')
            cards = soup.find_all("li")
            print(f"Found {len(cards)} job cards in LinkedIn search response.")
            
            cards = cards[:limit]
            
            parsed_cards = []
            for card in cards:
                job_id_elem = card.find("div", class_=self._BASE_CARD_PATTERN)
                job_id = ""
                if job_id_elem and job_id_elem.has_attr("data-entity-urn"):
                    urn = job_id_elem["data-entity-urn"]
                    job_id = urn.split(":")[-1]
                if not job_id:
                    a_elem = card.find("a", class_=self._FULL_LINK_PATTERN)
                    if a_elem and a_elem.has_attr("data-id"):
                        job_id = a_elem["data-id"]
                
                title_elem = card.find("h3", class_=self._TITLE_PATTERN)
                title = title_elem.get_text().strip() if title_elem else ""
                
                company_elem = card.find("h4", class_=self._SUBTITLE_PATTERN)
                company = company_elem.get_text().strip() if company_elem else ""
                
                location_elem = card.find("span", class_=self._LOCATION_PATTERN)
                location_name = location_elem.get_text().strip() if location_elem else ""
                
                link_elem = card.find("a", class_=self._FULL_LINK_PATTERN)
                job_url = link_elem["href"].split("?")[0] if link_elem and link_elem.has_attr("href") else ""
                if not job_url and job_id:
                    job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                
                if not title or not company:
                    continue
                
                parsed_cards.append({
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location_name": location_name,
                    "job_url": job_url
                })

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self.fetch_job_description, c["job_id"]): c 
                    for c in parsed_cards
                }
                
                for future in futures:
                    c = futures[future]
                    try:
                        about_job = future.result()
                    except Exception as exc:
                        print(f"Error resolving future for job ID {c['job_id']}: {exc}")
                        about_job = ""
                    
                    if not about_job:
                        about_job = f"Job title: {c['title']}. Company: {c['company']}. Location: {c['location_name']}. For full description and to apply, please view: {c['job_url']}"
                    
                    job_obj = Job(
                        title=c["title"],
                        company=c["company"],
                        location=c["location_name"],
                        about_job=about_job,
                        site=["LinkedIn"],
                        url=c["job_url"],
                        job_id=c["job_id"]
                    )
                    scraped_jobs.append(job_obj)
                
        except Exception as e:
            print(f"Error scraping LinkedIn: {e}")
            
        return scraped_jobs
