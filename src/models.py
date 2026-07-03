from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class Job:
    title: str
    company: str
    location: str
    about_job: str
    site: List[str]
    url: Optional[str] = None
    salary: Optional[str] = None
    experience_required: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    job_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Converts Job dataclass to a dictionary for JSON/MongoDB storage."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "about_job": self.about_job,
            # Output site as a comma-separated string if it is a list
            "site": ", ".join(self.site) if isinstance(self.site, list) else self.site,
            "url": self.url,
            "salary": self.salary,
            "experience_required": self.experience_required,
            "scraped_at": self.scraped_at.isoformat() if isinstance(self.scraped_at, datetime) else self.scraped_at,
            "job_id": self.job_id
        }
