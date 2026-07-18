import os
import json
from typing import List, Dict, Any, Tuple
from src.tailor_cv.pdf_parser import extract_text_from_pdf
from src.tailor_cv.claude_client import ClaudeClient, accumulate_job_tokens

def run_cv_matching(
    cv_path: str,
    jobs_json_path: str,
    api_key: str = None,
    model: str = "claude-3-5-haiku-20241022"
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
    cv_text = extract_text_from_pdf(cv_path)
    
    # 2. Load jobs
    with open(jobs_json_path, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    
    # 3. Initialize Claude Client
    client = ClaudeClient(api_key=api_key, model=model)
    
    all_results = []
    matched_results = []
    
    headers = ["No", "Job Title", "Company", "Status", "Score"]
    col_widths = [4, 35, 20, 18, 7]
    format_str = "| " + " | ".join([f"{{:<{w}}}" for w in col_widths]) + " |"
    sep_str = "|-" + "-|-".join(["-" * w for w in col_widths]) + "-|"
    
    print("\n" + "=" * 90)
    print("EVALUATING JOBS AGAINST CV USING LLM")
    print("=" * 90)
    print(format_str.format(*headers))
    print(sep_str)
    
    for idx, job in enumerate(jobs, 1):
        title = job.get("title", "Unknown Title")
        company = job.get("company", "Unknown Company")
        
        # Check if job is already scored (caching)
        existing_score = job.get("score")
        existing_explanation = job.get("explanation")
        
        if existing_score is not None and existing_explanation:
            status_str = "Skipping (Cached)"
            score = existing_score
            explanation = existing_explanation
        else:
            status_str = "Scored (API Call)"
            
            # Get score from LLM
            res = client.get_match_score(cv_text, job)
            score = res["score"]
            explanation = res["explanation"]
            
            # Save score and explanation back to job dictionary
            job["score"] = score
            job["explanation"] = explanation
            accumulate_job_tokens(job, res["usage"])
            
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
                
        # Truncate strings to fit columns
        t_title = title[:32] + "..." if len(title) > 35 else title
        t_company = company[:17] + "..." if len(company) > 20 else company
        score_str = f"{score}/10" if score is not None else "Pending"
        print(format_str.format(str(idx), t_title, t_company, status_str, score_str))
        
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
            
    print("-" * len(sep_str) + "\n")
    
    return all_results, matched_results
