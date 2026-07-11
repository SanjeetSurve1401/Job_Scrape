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

    def __post_init__(self):
        import re

        def clean_text(text: str) -> str:
            if not text:
                return text
            
            # Split by newline first to clean individual lines
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            cleaned_lines = []
            for line in lines:
                # Check for inline duplication (e.g., "Junior Software DeveloperJunior Software Developer")
                length = len(line)
                if length % 2 == 0:
                    half = length // 2
                    if line[:half] == line[half:]:
                        line = line[:half]
                
                # Check if words are duplicated
                words = line.split()
                w_len = len(words)
                if w_len % 2 == 0:
                    half_w = w_len // 2
                    if words[:half_w] == words[half_w:]:
                        line = " ".join(words[:half_w])
                
                # Remove "with verification" or "verification" if they are visual badge leftovers
                line = re.sub(r"\bwith verification\b", "", line, flags=re.IGNORECASE).strip()
                line = re.sub(r"\bverification\b", "", line, flags=re.IGNORECASE).strip()
                
                # Standardize spaces
                line = re.sub(r'\s+', ' ', line).strip()
                
                if line and line not in cleaned_lines:
                    cleaned_lines.append(line)
            
            return " ".join(cleaned_lines) if cleaned_lines else ""

        self.title = clean_text(self.title)
        self.company = clean_text(self.company)
        self.location = clean_text(self.location)

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
