from typing import Optional
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from src.scrapers.base import BaseScraper
from src.models import Job
from src.config import Config

class GlassdoorScraper(BaseScraper):
    def __init__(self):
        self.search_html_path = "glassdoor_search.html"
        self.session_path = Config.GLASSDOOR_SESSION_PATH
        self.headers = {}
        self.load_session()

    def load_session(self):
        """Loads session cookies and User-Agent from glassdoor_session.json."""
        if os.path.exists(self.session_path):
            try:
                with open(self.session_path, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                # Construct headers
                self.headers = {
                    "User-Agent": session_data.get("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0"),
                    "Cookie": session_data.get("Cookie", "")
                }
                print("Glassdoor session cookies loaded successfully.")
            except Exception as e:
                print(f"Warning: Failed to load Glassdoor session file: {e}")
        else:
            print(f"Warning: Glassdoor session file '{self.session_path}' not found. Live requests will fail.")

    def _extract_nextjs_payload(self, html_content: str) -> str:
        """Concatenates Next.js App Router chunks from self.__next_f.push calls."""
        push_pattern = re.compile(r'self\.__next_f\.push\(\[\s*\d+\s*,\s*"(.*?)"\s*\]\)', re.DOTALL)
        pushes = push_pattern.findall(html_content)
        
        full_payload = ""
        for p in pushes:
            # Unescape JS string literal escapes
            unescaped = p.replace('\\"', '"').replace('\\\\', '\\').replace('\\/', '/').replace('\\n', '\n')
            full_payload += unescaped
        return full_payload

    def _extract_json_array(self, text: str, start_pos: int) -> Optional[str]:
        """Extracts a JSON array matching bracket counts starting at start_pos."""
        pos = text.find('[', start_pos)
        if pos == -1:
            return None
            
        bracket_count = 0
        in_string = False
        escape = False
        
        for i in range(pos, len(text)):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        return text[pos:i+1]
        return None

    def fetch_live_description(self, url: str) -> str:
        """Fetches the job details page live using session cookies to get the full description."""
        if not url or not self.headers.get("Cookie"):
            return ""
            
        try:
            print(f"Fetching live Glassdoor job description from: {url}")
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Try common description classes/selectors on Glassdoor
                desc_selectors = [
                    {"class_": re.compile("jobDescriptionContent")},
                    {"class_": re.compile("JobDetails_jobDescription")},
                    {"id": "JobDescriptionContainer"},
                    {"data-test": "jobDescription"}
                ]
                
                for selector in desc_selectors:
                    desc_div = soup.find("div", **selector)
                    if desc_div:
                        return desc_div.get_text(separator="\n").strip()
                
                # Fallback to general article or main body text if selectors missed
                main_article = soup.find("article")
                if main_article:
                    return main_article.get_text(separator="\n").strip()
                    
                # Look for paragraph text in the body
                paragraphs = soup.find_all("p")
                if len(paragraphs) > 5:
                    return "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
                    
            elif response.status_code == 403:
                print(f"Glassdoor live fetch returned 403 (Forbidden). Most likely Cloudflare protection.")
            else:
                print(f"Glassdoor live fetch returned status code: {response.status_code}")
                
        except Exception as e:
            print(f"Error fetching live Glassdoor description: {e}")
            
        return ""

    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> list[Job]:
        """Scrapes Glassdoor jobs using local glassdoor_search.html and live sessions."""
        print(f"Running Glassdoor Scraper for Role: '{role}', Location: '{location}'")
        
        if not os.path.exists(self.search_html_path):
            print(f"Error: Local Glassdoor HTML file '{self.search_html_path}' not found.")
            return []
            
        with open(self.search_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # Parse the Next.js hydration payload
        payload = self._extract_nextjs_payload(html_content)
        if not payload:
            print("Failed to extract hydration state from local Glassdoor HTML.")
            return []
            
        # Locate the job listings array
        search_term = '"searchResultsData":{"jobListings":'
        idx = payload.find(search_term)
        if idx == -1:
            print("Could not find searchResultsData in hydration state.")
            return []
            
        array_search = '"jobListings":['
        array_idx = payload.find(array_search, idx)
        if array_idx == -1:
            print("Could not find jobListings array in hydration state.")
            return []
            
        array_start = array_idx + len('"jobListings":') - 1
        array_str = self._extract_json_array(payload, array_start)
        
        if not array_str:
            print("Failed to parse JSON jobListings array.")
            return []
            
        try:
            job_listings = json.loads(array_str)
            # Limit the listings we parse to speed up live details queries
            job_listings = job_listings[:limit]
        except Exception as e:
            print(f"JSON parsing error: {e}")
            return []
            
        print(f"Found {len(job_listings)} job listings in Glassdoor local file.")
        
        # We also need to extract any descriptions embedded in the HTML file
        # We saw that there is a description in pushes that we can find
        embedded_desc = ""
        # Look for standard HTML description tag text
        soup = BeautifulSoup(html_content, 'lxml')
        desc_div = soup.find("div", class_=re.compile("JobDetails_jobDescription"))
        if desc_div:
            embedded_desc = desc_div.get_text(separator="\n").strip()
            
        scraped_jobs = []
        for item in job_listings:
            jobview = item.get("jobview", {})
            header = jobview.get("header", {})
            job_details = jobview.get("job", {})
            
            title = header.get("jobTitleText", "")
            company = header.get("employer", {}).get("name", "")
            if not company:
                company = header.get("employer", {}).get("shortName", "")
            location_name = header.get("locationName", "")
            
            # Construct URL
            url = header.get("seoJobLink")
            if url and not url.startswith("http"):
                url = "https://www.glassdoor.co.in" + url
                
            # Handle salary
            salary_info = header.get("payPeriodAdjustedPay")
            salary = None
            if salary_info:
                p10 = salary_info.get("p10")
                p50 = salary_info.get("p50")
                p90 = salary_info.get("p90")
                currency = header.get("payCurrency", "INR")
                if p10 and p90:
                    salary = f"{currency} {p10} - {p90}"
                elif p50:
                    salary = f"{currency} {p50}"
            
            # Fetch job description:
            # 1. If it's the active job (Junior QA Engineer), it's likely matching the embedded description.
            # 2. Otherwise, try fetching live.
            # 3. Fall back to a placeholder indicating details link.
            about_job = ""
            if title == "Junior QA Engineer" and embedded_desc:
                about_job = embedded_desc
            else:
                # Try fetching live
                about_job = self.fetch_live_description(url)
                
            if not about_job:
                about_job = f"Job title: {title}. Company: {company}. Location: {location_name}. For full description and to apply, please view: {url}"
                
            job_obj = Job(
                title=title,
                company=company,
                location=location_name,
                about_job=about_job,
                site=["Glassdoor"],
                url=url,
                salary=salary,
                job_id=str(job_details.get("listingId", ""))
            )
            scraped_jobs.append(job_obj)
            
        return scraped_jobs
