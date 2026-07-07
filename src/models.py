import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    job_id: Optional[str] = None
    score: Optional[int] = None
    explanation: Optional[str] = None
    ats_score: Optional[str] = None

    def dedup_key(self) -> str:
        """
        Generates a deterministic dedup key from title + company + location.
        Used for O(log n) indexed lookups instead of O(n) regex scans.
        """
        normalized = f"{self.title.strip().lower()}|{self.company.strip().lower()}|{self.location.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """Converts Job dataclass to a dictionary for JSON/MongoDB storage."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "about_job": self.about_job,
            "site": ", ".join(self.site) if isinstance(self.site, list) else self.site,
            "url": self.url,
            "salary": self.salary,
            "experience_required": self.experience_required,
            "scraped_at": self.scraped_at.isoformat() if isinstance(self.scraped_at, datetime) else self.scraped_at,
            "job_id": self.job_id,
            "dedup_key": self.dedup_key(),
            "score": self.score,
            "explanation": self.explanation,
            "ats_score": self.ats_score
        }
