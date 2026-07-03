import os
import json
import re
import requests
from bs4 import BeautifulSoup
from src.scrapers.base import BaseScraper
from src.models import Job
from src.config import Config

class LinkedInScraper(BaseScraper):
    def __init__(self):
        self.cookies_path = Config.LINKEDIN_COOKIES_PATH
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.session.headers.update(self.headers)
        self.load_cookies()

    def load_cookies(self):
        """Loads cookies from linkedin_cookies.json if it exists."""
        if os.path.exists(self.cookies_path):
            try:
                with open(self.cookies_path, 'r', encoding='utf-8') as f:
                    cookies_data = json.load(f)
                
                # Check cookie format (list of dicts vs dict of key-values)
                if isinstance(cookies_data, list):
                    for cookie in cookies_data:
                        self.session.cookies.set(cookie.get("name"), cookie.get("value"), domain=cookie.get("domain", ".linkedin.com"))
                elif isinstance(cookies_data, dict):
                    for name, value in cookies_data.items():
                        self.session.cookies.set(name, value, domain=".linkedin.com")
                print("LinkedIn session cookies loaded successfully.")
            except Exception as e:
                print(f"Warning: Failed to load LinkedIn cookies: {e}")
        else:
            print(f"Warning: LinkedIn cookies file '{self.cookies_path}' not found. Scraping as guest.")

    def fetch_job_description(self, job_id: str) -> str:
        """Fetches the detailed job description HTML page and extracts text."""
        if not job_id:
            return ""
            
        # LinkedIn has a clean endpoint for guest/logged-in card content
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobCardContent/{job_id}"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                # The description is usually in a div or section
                desc_section = soup.find("div", class_="show-more-less-html__markup")
                if not desc_section:
                    desc_section = soup.find("section", class_="description")
                if not desc_section:
                    desc_section = soup
                    
                return desc_section.get_text(separator="\n").strip()
            else:
                # Try regular view URL
                url_view = f"https://www.linkedin.com/jobs/view/{job_id}"
                response_view = self.session.get(url_view, timeout=10)
                if response_view.status_code == 200:
                    soup = BeautifulSoup(response_view.text, 'lxml')
                    # Look for job description in main pages
                    desc_div = soup.find("div", class_="description__text")
                    if not desc_div:
                        desc_div = soup.find("div", class_=re.compile("show-more-less-html__markup"))
                    if desc_div:
                        return desc_div.get_text(separator="\n").strip()
        except Exception as e:
            print(f"Error fetching LinkedIn job description for ID {job_id}: {e}")
            
        return ""

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> list[Job]:
        """Scrapes LinkedIn jobs matching the search query parameters."""
        print(f"Running LinkedIn Scraper for Role: '{role}', Location: '{location}'")
        
        # Prepare parameters
        query_role = requests.utils.quote(role)
        query_location = requests.utils.quote(location)
        
        # LinkedIn public search API endpoint (robust for fetching lists of jobs)
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
            
            # Slice cards to limit search time
            cards = cards[:limit]
            
            for card in cards:
                # Extract job ID
                job_id_elem = card.find("div", class_=re.compile("base-card"))
                job_id = ""
                if job_id_elem and job_id_elem.has_attr("data-entity-urn"):
                    urn = job_id_elem["data-entity-urn"]
                    job_id = urn.split(":")[-1]
                if not job_id:
                    # Try alternative data-id
                    a_elem = card.find("a", class_=re.compile("base-card__full-link"))
                    if a_elem and a_elem.has_attr("data-id"):
                        job_id = a_elem["data-id"]
                
                # Title
                title_elem = card.find("h3", class_=re.compile("base-search-card__title"))
                title = title_elem.get_text().strip() if title_elem else ""
                
                # Company
                company_elem = card.find("h4", class_=re.compile("base-search-card__subtitle"))
                company = company_elem.get_text().strip() if company_elem else ""
                
                # Location
                location_elem = card.find("span", class_=re.compile("job-search-card__location"))
                location_name = location_elem.get_text().strip() if location_elem else ""
                
                # Job URL
                link_elem = card.find("a", class_=re.compile("base-card__full-link"))
                job_url = link_elem["href"].split("?")[0] if link_elem and link_elem.has_attr("href") else ""
                if not job_url and job_id:
                    job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                
                if not title or not company:
                    continue
                    
                # Fetch full description
                about_job = self.fetch_job_description(job_id)
                if not about_job:
                    about_job = f"Job title: {title}. Company: {company}. Location: {location_name}. For full description and to apply, please view: {job_url}"
                    
                job_obj = Job(
                    title=title,
                    company=company,
                    location=location_name,
                    about_job=about_job,
                    site=["LinkedIn"],
                    url=job_url,
                    job_id=job_id
                )
                scraped_jobs.append(job_obj)
                
        except Exception as e:
            print(f"Error scraping LinkedIn: {e}")
            
        return scraped_jobs
