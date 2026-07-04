import re
from typing import Optional, List, Tuple, Dict
from src.interfaces import VerifierInterface
from src.models import Job

class JobVerifier(VerifierInterface):
    # Precompile Regex patterns at class level to avoid compiling them on every function call
    _RANGE_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)')
    _PLUS_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*\+')
    _SINGLE_PATTERN = re.compile(r'(\d+(?:\.\d+)?)')
    
    _TEXT_EXP_PATTERNS = [
        re.compile(r'(\d+)\s*(?:-|to)\s*(\d+)\s*(?:years?|yrs?|years? of experience|yrs? of experience)\b'),
        re.compile(r'(\d+)\s*\+\s*(?:years?|yrs?)\b'),
        re.compile(r'(?:experience of|requires|minimum|at least)\s*(\d+)\s*(?:years?|yrs?)\b'),
        re.compile(r'(\d+)\s*(?:years?|yrs?)\s*(?:of)?\s*(?:manual|automation|software|relevant)?\s*(?:experience|testing|development)\b')
    ]

    _STOP_WORDS = {"and", "or", "for", "with", "jobs", "in", "of", "the", "a", "an", "at"}

    # Default synonyms dictionary for extensible matching
    DEFAULT_SYNONYMS = {
        "qa": ["quality assurance", "testing", "tester", "test"],
        "quality assurance": ["qa", "testing", "tester", "test"],
        "developer": ["engineer", "programmer", "coder"],
        "engineer": ["developer", "programmer"],
    }

    # Region relations mapping search cities to their states and country descriptors
    # This allows smart matching for state/country abbreviations returned by scrapers (e.g. MH, IN)
    _REGION_RELATIONS = {
        "pune": {"pune", "mh", "maharashtra", "india", "in", "pimpri", "chinchwad"},
        "mumbai": {"mumbai", "mh", "maharashtra", "india", "in", "navi mumbai", "thane"},
        "bangalore": {"bangalore", "bengaluru", "ka", "karnataka", "india", "in"},
        "bengaluru": {"bangalore", "bengaluru", "ka", "karnataka", "india", "in"},
        "hyderabad": {"hyderabad", "tg", "telangana", "ap", "andhra pradesh", "india", "in"},
        "chennai": {"chennai", "tn", "tamil nadu", "india", "in"},
        "noida": {"noida", "up", "uttar pradesh", "ncr", "delhi", "india", "in"},
        "gurgaon": {"gurgaon", "hr", "haryana", "ncr", "delhi", "india", "in"},
        "delhi": {"delhi", "ncr", "india", "in"},
    }

    def __init__(self, synonyms: Optional[Dict[str, List[str]]] = None):
        self.synonyms = synonyms if synonyms is not None else self.DEFAULT_SYNONYMS

    def parse_experience_string(self, exp_str: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Parses an experience string (e.g., '1-3 years', '3+ years', 'Entry Level') 
        and returns a tuple of (min_years, max_years).
        """
        if not exp_str:
            return None, None
            
        exp_str = exp_str.lower().strip()
        
        # Check for common non-numeric descriptions (including India-specific 'fresher' and others)
        if "entry" in exp_str or "junior" in exp_str or "intern" in exp_str or "fresher" in exp_str:
            return 0.0, 2.0
        if "mid" in exp_str or "associate" in exp_str:
            return 2.0, 5.0
        if "senior" in exp_str or "lead" in exp_str:
            return 5.0, 15.0
        if "director" in exp_str or "executive" in exp_str:
            return 8.0, 25.0
            
        # Match pattern "X - Y" or "X to Y"
        range_match = self._RANGE_PATTERN.search(exp_str)
        if range_match:
            return float(range_match.group(1)), float(range_match.group(2))
            
        # Match pattern "X+" or "X+ years"
        plus_match = self._PLUS_PATTERN.search(exp_str)
        if plus_match:
            return float(plus_match.group(1)), 99.0
            
        # Match single number "X years" or just "X"
        single_match = self._SINGLE_PATTERN.search(exp_str)
        if single_match:
            val = float(single_match.group(1))
            return max(0.0, val - 1.0), val + 2.0
            
        return None, None

    def extract_experience_from_text(self, text: str) -> List[Tuple[float, float]]:
        """
        Scans a job description text to find experience patterns and extracts them.
        Returns a list of ranges (min_years, max_years).
        """
        if not text:
            return []
            
        text = text.lower()
        ranges = []
        
        for pattern in self._TEXT_EXP_PATTERNS:
            for match in pattern.finditer(text):
                groups = match.groups()
                try:
                    if len(groups) == 2 and groups[1] is not None:
                        ranges.append((float(groups[0]), float(groups[1])))
                    elif len(groups) >= 1 and groups[0] is not None:
                        ranges.append((float(groups[0]), float(groups[0]) + 3.0))
                except ValueError:
                    continue
                    
        return ranges

    def _verify_location(self, req_location: str, job_location: str) -> bool:
        """Helper to match location names case-insensitively, supporting abbreviations."""
        loc_lower = req_location.lower().strip()
        job_loc_lower = job_location.lower().strip()

        # Handle Remote queries
        if "remote" in loc_lower:
            return "remote" in job_loc_lower or "work from home" in job_loc_lower

        # Exact substring matches
        if loc_lower in job_loc_lower or job_loc_lower in loc_lower:
            return True

        # Treat remote jobs as valid matches for city-based searches (highly common)
        if "remote" in job_loc_lower or "work from home" in job_loc_lower:
            return True

        # Try region abbreviation lookup
        if loc_lower in self._REGION_RELATIONS:
            allowed_tokens = self._REGION_RELATIONS[loc_lower]
            # Split job location into tokens (words) to do matching (e.g. "MH" -> {"mh"})
            job_tokens = set(re.findall(r'\b[a-z]{2,}\b', job_loc_lower))
            # Handle 2-letter state codes like 'mh'
            two_letter_match = any(tok in allowed_tokens for tok in re.findall(r'\b[a-z]{2}\b', job_loc_lower))
            
            if two_letter_match or (job_tokens & allowed_tokens):
                return True

        return False

    def verify(self, job: Job, req_role: str, req_location: str, req_experience: str) -> bool:
        """
        Verifies if a scraped Job matches the requested Role, Location, and Experience.
        """
        # 1. Verify Job Role / Title Match
        title_lower = job.title.lower()
        role_lower = req_role.lower()
        
        role_keywords = [w.strip() for w in role_lower.split() if w.strip() not in self._STOP_WORDS]
        
        if not role_keywords:
            role_keywords = [role_lower]
            
        # Count keyword matches
        match_count = sum(1 for kw in role_keywords if kw in title_lower)
        
        if match_count == 0:
            # Check for synonyms
            synonym_match = False
            for kw in role_keywords:
                if kw in self.synonyms:
                    for syn in self.synonyms[kw]:
                        if syn in title_lower:
                            synonym_match = True
                            break
                if synonym_match:
                    break
            if not synonym_match:
                return False

        # 2. Verify Location Match
        if not self._verify_location(req_location, job.location):
            return False

        # 3. Verify Experience Match
        req_min, req_max = self.parse_experience_string(req_experience)
        
        if req_min is not None:
            # Check if job is from Indeed (site list/string contains "Indeed")
            is_indeed = False
            if isinstance(job.site, list):
                is_indeed = any(s.strip().lower() == "indeed" for s in job.site)
            elif isinstance(job.site, str):
                is_indeed = "indeed" in job.site.lower()
                
            # If the job is from Indeed and has an explicit experience range metadata
            if is_indeed and job.experience_required:
                job_min, job_max = self.parse_experience_string(job.experience_required)
                if job_min is not None:
                    overlap_min = max(req_min, job_min)
                    overlap_max = min(req_max if req_max is not None else 99.0, job_max if job_max is not None else 99.0)
                    if overlap_min <= overlap_max:
                        return True
                    else:
                        # Indeed explicitly lists experience requirements; if they don't overlap, reject it
                        return False
            
            # Fallback for non-Indeed or when Indeed metadata is not available/parsable
            job_exp_ranges = self.extract_experience_from_text(job.about_job)
            if job_exp_ranges:
                overlap = False
                for job_min, job_max in job_exp_ranges:
                    overlap_min = max(req_min, job_min)
                    overlap_max = min(req_max if req_max is not None else 99.0, job_max if job_max is not None else 99.0)
                    if overlap_min <= overlap_max:
                        overlap = True
                        break
                if not overlap:
                    return False
                    
        return True
