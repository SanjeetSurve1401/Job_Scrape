import re
import requests
from bs4 import BeautifulSoup
from src.scrapers.base import BaseScraper
from src.models import Job

class IndeedScraper(BaseScraper):
    def __init__(self):
        self.session = requests.Session()
        # Rotate user-agent to look like a modern browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "Referer": "https://www.google.com/",
            "DNT": "1"
        }
        self.session.headers.update(self.headers)

    def fetch_job_description(self, jk: str) -> str:
        """Fetches the job details page for a specific Indeed job key."""
        if not jk:
            return ""
            
        url = f"https://www.indeed.com/viewjob?jk={jk}"
        try:
            response = self.session.get(url, timeout=10)
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

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> list[Job]:
        """Scrapes Indeed jobs matching the role and location."""
        print(f"Running Indeed Scraper for Role: '{role}', Location: '{location}'")
        
        query_role = requests.utils.quote(role)
        query_location = requests.utils.quote(location)
        
        # Indeed India or US based on location (using indeed.com as fallback, or in.indeed.com for India context)
        base_url = "https://in.indeed.com" if "india" in location.lower() or "pune" in location.lower() or "mumbai" in location.lower() else "https://www.indeed.com"
        url = f"{base_url}/jobs?q={query_role}&l={query_location}"
        
        scraped_jobs = []
        try:
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 403 or response.status_code == 503:
                print("Indeed returned 403/503. The request was blocked by Cloudflare anti-bot system. Skipping Indeed live search.")
                return []
                
            if response.status_code != 200:
                print(f"Indeed search returned status code: {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Indeed job card links or containers typically have class job_seen_beacon or contain data-jk
            job_cards = soup.find_all("div", class_=re.compile("job_seen_beacon"))
            if not job_cards:
                # Alternate selectors
                job_cards = soup.find_all("td", class_="resultContent")
                
            print(f"Found {len(job_cards)} job cards in Indeed search response.")
            
            # Limit the job cards processed
            job_cards = job_cards[:limit]
            
            for card in job_cards:
                # Find the job title link which contains data-jk or href
                a_link = card.find("a", href=True)
                if not a_link:
                    continue
                    
                href = a_link["href"]
                # Extract jk (job key)
                jk_match = re.search(r'jk=([a-f0-9]+)', href)
                jk = jk_match.group(1) if jk_match else ""
                
                if not jk:
                    # Try getting from parent tags
                    parent = card.find_parent(attrs={"data-jk": True})
                    if parent:
                        jk = parent["data-jk"]
                        
                if not jk:
                    continue
                    
                # Title
                title_elem = card.find("h2", class_=re.compile("jobTitle"))
                if not title_elem:
                    title_elem = card.find(re.compile("h[23]"))
                title = title_elem.get_text().strip() if title_elem else ""
                # Indeed sometimes adds "new" text inside the title element, clean it up
                title = re.sub(r'^new\s+', '', title, flags=re.IGNORECASE)
                
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
                salary_elem = card.find("div", class_=re.compile("salary-snippet"))
                if not salary_elem:
                    salary_elem = card.find("div", class_=re.compile("metadata"))
                salary = salary_elem.get_text().strip() if salary_elem else None
                
                job_url = f"{base_url}/viewjob?jk={jk}"
                
                if not title or not company:
                    continue
                    
                # Fetch full description
                about_job = self.fetch_job_description(jk)
                if not about_job:
                    about_job = f"Job title: {title}. Company: {company}. Location: {location_name}. For full description and to apply, please view: {job_url}"
                    
                job_obj = Job(
                    title=title,
                    company=company,
                    location=location_name,
                    about_job=about_job,
                    site=["Indeed"],
                    url=job_url,
                    salary=salary,
                    job_id=jk
                )
                scraped_jobs.append(job_obj)
                
        except Exception as e:
            print(f"Error scraping Indeed: {e}")
            
        return scraped_jobs
