from abc import ABC, abstractmethod
from typing import List
from src.models import Job

class BaseScraper(ABC):
    @abstractmethod
    def scrape(self, role: str, location: str, experience: str, limit: int = 10) -> List[Job]:
        """
        Scrapes job postings matching the criteria from the source.
        
        Args:
            role (str): Job role / title (e.g. 'Software QA Engineer')
            location (str): Location (e.g. 'Pune')
            experience (str): Required experience (e.g. '1-3 years')
            limit (int): Maximum number of listings to retrieve (for demo/speed)
            
        Returns:
            List[Job]: List of scraped Job objects.
        """
        pass
