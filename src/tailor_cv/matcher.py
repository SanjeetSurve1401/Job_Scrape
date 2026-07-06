import os
import json
from typing import List, Dict, Any, Tuple
from src.tailor_cv.pdf_parser import extract_text_from_pdf
from src.tailor_cv.groq_client import GroqClient

def run_cv_matching(
    cv_path: str,
    jobs_json_path: str,
    api_key: str = None,
    model: str = "llama-3.1-8b-instant"
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Reads the CV from a PDF file, loops over job details in a JSON file,
    sends details to Groq to score them, and separates matches with score > 6.
    
    Implements:
    - Caching: skips jobs already scored in the JSON file.
    - Incremental Updates: saves new scores to the JSON file immediately.
    """
    if not os.path.exists(cv_path):
        raise FileNotFoundError(f"CV file not found at: {cv_path}")
    
    if not os.path.exists(jobs_json_path):
        raise FileNotFoundError(f"Scraped jobs file not found at: {jobs_json_path}")
    
    # 1. Convert CV PDF to text
    print(f"\n[CV Matcher] Extracting text from CV: {cv_path}...")
    cv_text = extract_text_from_pdf(cv_path)
    print(f"[CV Matcher] Extracted {len(cv_text)} characters from CV.")
    
    # 2. Load jobs
    print(f"[CV Matcher] Loading jobs from {jobs_json_path}...")
    with open(jobs_json_path, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    print(f"[CV Matcher] Loaded {len(jobs)} jobs.")
    
    # 3. Initialize Groq Client
    client = GroqClient(api_key=api_key, model=model)
    
    all_results = []
    matched_results = []
    
    print("\n[CV Matcher] Evaluating jobs against CV using LLM...")
    print("=" * 60)
    
    for idx, job in enumerate(jobs, 1):
        title = job.get("title", "Unknown Title")
        company = job.get("company", "Unknown Company")
        
        # Check if job is already scored (caching)
        existing_score = job.get("score")
        existing_explanation = job.get("explanation")
        
        if existing_score is not None and existing_explanation:
            print(f"[{idx}/{len(jobs)}] Skipping (Cached): '{title}' at {company} -> Score: {existing_score}/10")
            score = existing_score
            explanation = existing_explanation
        else:
            print(f"[{idx}/{len(jobs)}] Scoring (API Call): '{title}' at {company}...")
            
            # Get score from LLM
            res = client.get_match_score(cv_text, job)
            score = res["score"]
            explanation = res["explanation"]
            
            # Save score and explanation back to job dictionary
            job["score"] = score
            job["explanation"] = explanation
            
            # Write updated jobs back to JSON file immediately
            try:
                with open(jobs_json_path, 'w', encoding='utf-8') as f:
                    json.dump(jobs, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"    [Warning] Failed to write updated score to file: {e}")
            
            # Respect rate limits by sleeping 6 seconds between actual API calls (10 requests per minute)
            if idx < len(jobs):
                import time
                time.sleep(6.0)
        
        job_result = {
            "sr_no": job.get("sr_no", idx),
            "title": title,
            "company": company,
            "score": score,
            "explanation": explanation,
            "url": job.get("url", ""),
            "location": job.get("location", "")
        }
        
        all_results.append(job_result)
        if score > 6:
            matched_results.append(job_result)
            
    print("=" * 60)
    print("[CV Matcher] Evaluation complete.\n")
    
    return all_results, matched_results
