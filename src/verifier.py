import re
from typing import Optional
from src.models import Job

class JobVerifier:
    @staticmethod
    def parse_experience_string(exp_str: str) -> tuple[Optional[float], Optional[float]]:
        """
        Parses an experience string (e.g., '1-3 years', '3+ years', 'Entry Level') 
        and returns a tuple of (min_years, max_years).
        """
        if not exp_str:
            return None, None
            
        exp_str = exp_str.lower().strip()
        
        # Check for common non-numeric descriptions
        if "entry" in exp_str or "junior" in exp_str or "intern" in exp_str:
            return 0.0, 2.0
        if "mid" in exp_str:
            return 2.0, 5.0
        if "senior" in exp_str or "lead" in exp_str:
            return 5.0, 15.0
            
        # Regex to find numbers: e.g. "1-3", "3+", "2 to 5"
        # Match pattern "X - Y" or "X to Y"
        range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)', exp_str)
        if range_match:
            return float(range_match.group(1)), float(range_match.group(2))
            
        # Match pattern "X+" or "X+ years"
        plus_match = re.search(r'(\d+(?:\.\d+)?)\s*\+', exp_str)
        if plus_match:
            return float(plus_match.group(1)), 99.0
            
        # Match single number "X years" or just "X"
        single_match = re.search(r'(\d+(?:\.\d+)?)', exp_str)
        if single_match:
            val = float(single_match.group(1))
            # Treat single value "3 years" as a range e.g. 0 to 3 or 3 to 5?
            # Let's say if user asks for "3 years", it means up to 3 or around 3 (e.g. 2 to 4)
            return max(0.0, val - 1.0), val + 2.0
            
        return None, None

    @staticmethod
    def extract_experience_from_text(text: str) -> list[tuple[float, float]]:
        """
        Scans a job description text to find experience patterns and extracts them.
        Returns a list of ranges (min_years, max_years).
        """
        if not text:
            return []
            
        text = text.lower()
        ranges = []
        
        # Look for patterns like "1-3 years", "2+ years", "3 to 5 yrs", "experience of 4 years", etc.
        patterns = [
            r'(\d+)\s*(?:-|to)\s*(\d+)\s*(?:years?|yrs?|years? of experience|yrs? of experience)\b',
            r'(\d+)\s*\+\s*(?:years?|yrs?)\b',
            r'(?:experience of|requires|minimum|at least)\s*(\d+)\s*(?:years?|yrs?)\b',
            r'(\d+)\s*(?:years?|yrs?)\s*(?:of)?\s*(?:manual|automation|software|relevant)?\s*(?:experience|testing|development)\b'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                groups = match.groups()
                try:
                    if len(groups) == 2 and groups[1] is not None:
                        ranges.append((float(groups[0]), float(groups[1])))
                    elif len(groups) >= 1 and groups[0] is not None:
                        ranges.append((float(groups[0]), float(groups[0]) + 3.0)) # default max to +3 years if + or min
                except ValueError:
                    continue
                    
        return ranges

    def verify(self, job: Job, req_role: str, req_location: str, req_experience: str) -> bool:
        """
        Verifies if a scraped Job matches the requested Role, Location, and Experience.
        
        Returns:
            True if the job matches all criteria, False otherwise.
        """
        # 1. Verify Job Role / Title Match
        # Split required role into keywords and check if at least one primary keyword is present in the title
        title_lower = job.title.lower()
        role_lower = req_role.lower()
        
        # Primary keywords (exclude generic words like "and", "or", "for", "with", "jobs")
        stop_words = {"and", "or", "for", "with", "jobs", "in", "of", "the", "a", "an", "at"}
        role_keywords = [w.strip() for w in role_lower.split() if w.strip() not in stop_words]
        
        if not role_keywords:
            # Fallback if no keywords (unlikely)
            role_keywords = [role_lower]
            
        # Count keyword matches
        match_count = sum(1 for kw in role_keywords if kw in title_lower)
        
        # For job titles, we want at least one key term to match (or more if the role is specific)
        # E.g. searching "Software QA Engineer" -> title "QA Engineer" matches (2 keywords matching: QA, Engineer)
        # Searching "React Developer" -> title "Frontend Developer (React)" matches
        # If match count is 0, this is definitely not the right job.
        if match_count == 0:
            # Check for common synonyms
            synonyms = {
                "qa": ["quality assurance", "testing", "tester", "test"],
                "quality assurance": ["qa", "testing", "tester", "test"],
                "developer": ["engineer", "programmer", "coder"],
                "engineer": ["developer", "programmer"],
            }
            # Check if any synonyms of search terms match
            synonym_match = False
            for kw in role_keywords:
                if kw in synonyms:
                    for syn in synonyms[kw]:
                        if syn in title_lower:
                            synonym_match = True
                            break
                if synonym_match:
                    break
            if not synonym_match:
                return False

        # 2. Verify Location Match
        # Check if requested location name is in the job location or vice versa
        loc_lower = req_location.lower().strip()
        job_loc_lower = job.location.lower().strip()
        
        # Handle "Remote" matching
        if "remote" in loc_lower:
            if "remote" not in job_loc_lower and "work from home" not in job_loc_lower:
                return False
        else:
            # If not searching for remote, check if requested location is a substring
            # E.g. "pune" in "pune, maharashtra"
            # Or handle cases like "india" in "pune, india"
            if loc_lower not in job_loc_lower and job_loc_lower not in loc_lower:
                # Let remote jobs pass as location match sometimes, but check if there's any state/country overlap
                # If they are completely different (e.g. "pune" vs "bangalore"), return False
                if "remote" not in job_loc_lower and "work from home" not in job_loc_lower:
                    return False

        # 3. Verify Experience Match
        # Parse the required experience range
        req_min, req_max = self.parse_experience_string(req_experience)
        
        if req_min is not None:
            # Extract experience requirements from the job description
            job_exp_ranges = self.extract_experience_from_text(job.about_job)
            
            # If the job description explicitly mentions experience requirements
            if job_exp_ranges:
                overlap = False
                for job_min, job_max in job_exp_ranges:
                    # Check for overlap between [req_min, req_max] and [job_min, job_max]
                    # Two ranges [A, B] and [C, D] overlap if max(A, C) <= min(B, D)
                    overlap_min = max(req_min, job_min)
                    overlap_max = min(req_max if req_max is not None else 99.0, job_max if job_max is not None else 99.0)
                    if overlap_min <= overlap_max:
                        overlap = True
                        break
                
                # If there's no overlap with the found ranges, filter it out
                if not overlap:
                    return False
                    
        return True
