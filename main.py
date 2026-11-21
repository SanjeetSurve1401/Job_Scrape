import argparse
import json
import os
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor
from src.config import Config
from src.database import DatabaseHandler, LocalDatabaseHandler
from src.interfaces import DatabaseInterface
from src.verifier import JobVerifier
from src.scrapers import get_scrapers
from src.models import Job
from src.tailor_cv.matcher import run_cv_matching
from src.graph import build_scraper_graph


def parse_args():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="SOLID Job Scraper for LinkedIn and Glassdoor")
    parser.add_argument("--role", type=str, default="Software QA Engineer", help="Job role to search for")
    parser.add_argument("--location", type=str, default="Pune", help="Location to search for")
    parser.add_argument("--experience", type=str, default="1-3 years", help="Required experience level (e.g., '1-3 years', 'Entry Level')")
    parser.add_argument("--output", type=str, default=None, help="Path to save the JSON output file")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save all outputs")
    parser.add_argument("--limit", type=int, default=15, help="Total max jobs to scrape across all sources (default: 15)")
    parser.add_argument("--cv", type=str, default=None, help="Path to your CV PDF file")
    parser.add_argument("--match-only", action="store_true", help="Only run CV matching on existing scraped jobs json file")
    parser.add_argument("--claude-model", type=str, default="claude haiku 4.5", help="Claude model to use for matching and tailoring")
    parser.add_argument("--groq-model", type=str, default=None, help="Deprecated: Use --claude-model instead")
    parser.add_argument("--openrouter-model", type=str, default=None, help="Deprecated: Use --claude-model instead")
    parser.add_argument("--sources", type=str, default="linkedin,glassdoor", help="Comma-separated list of job sources to scrape (default: 'linkedin,glassdoor')")
    parser.add_argument("--manual", type=str, default=None, help="Path to a manual JSON file with company jobs to tailor directly without scraping")
    
    args = parser.parse_args()
    if not args.groq_model:
        args.groq_model = args.claude_model
    if not args.openrouter_model:
        args.openrouter_model = args.claude_model
    return args

def execute_scraping(scrapers: list, args, limit: int) -> List[Job]:
    """Runs all discovered scrapers in parallel and collects raw jobs, distributing the limit."""
    all_scraped_jobs = []
    total_scrapers = len(scrapers)
    if total_scrapers == 0:
        return []

    # Calculate equal share limit for each scraper using ceiling division
    scraper_limit = max(1, (limit + total_scrapers - 1) // total_scrapers)

    def run_one_scraper(scraper_cls):
        try:
            scraper = scraper_cls()
            scraper_name = scraper.__class__.__name__
            print(f"\n[Scraping] Launching {scraper_name} in parallel (Limit: {scraper_limit})...")
            jobs = scraper.scrape(args.role, args.location, args.experience, limit=scraper_limit)
            print(f"[Scraping] {scraper_name} returned {len(jobs)} jobs.")
            return jobs
        except Exception as e:
            scraper_name = scraper_cls.__name__
            print(f"[Error] Scraper {scraper_name} failed: {e}")
            return []

    # Execute in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=total_scrapers) as executor:
        results = executor.map(run_one_scraper, scrapers)

    for jobs in results:
        all_scraped_jobs.extend(jobs)

    return all_scraped_jobs[:limit]



def process_and_save_jobs(db: DatabaseInterface, verifier: JobVerifier, raw_jobs: List[Job], args, cv_text: str = "") -> Tuple[int, int, int, List[dict]]:
    """Filters, verifies, scores inline via Groq, and saves scraped jobs to database."""
    verified_jobs_count = 0
    new_jobs_inserted = 0
    existing_jobs_updated = 0
    saved_jobs_list = []

    # Instantiate ClaudeClient if matching is requested
    client = None
    if cv_text:
        from src.tailor_cv.claude_client import get_llm_client
        client = get_llm_client(model=args.groq_model)

    from src.database import DatabaseHandler
    is_mongodb = isinstance(db, DatabaseHandler)

    print("\n[Verifying, Scoring & Saving] Processing jobs...")
    for job in raw_jobs:
        if verifier.verify(job, args.role, args.location, args.experience):
            verified_jobs_count += 1
            
            # 1. Check if job is already in the database and already has a score (caching)
            dedup_key = job.dedup_key()
            existing_doc = db.find_job_by_key(dedup_key)
            
            score = None
            explanation = None
            
            if existing_doc and existing_doc.get("score") is not None:
                score = existing_doc.get("score")
                explanation = existing_doc.get("explanation")
                print(f"  [Cached Score] '{job.title}' at {job.company} -> Score: {score}/10")
            elif client:
                print(f"  [Scoring API Call] '{job.title}' at {job.company}...")
                res = client.get_match_score(cv_text, job.to_dict())
                score = res["score"]
                explanation = res["explanation"]
                
                # Capture token usage
                from src.tailor_cv.claude_client import accumulate_job_tokens
                job_dict = job.to_dict()
                accumulate_job_tokens(job_dict, res["usage"])
                job.tokens_consumed = job_dict.get("tokens_consumed")
                
                # Respect rate limit between Claude API calls
                import time
                time.sleep(2.0)
                
            job.score = score
            job.explanation = explanation
            
            # Determine if we should save to DB (MongoDB/Local)
            # MongoDB Mode: only save if score > 6 (or if matching was skipped)
            # Local Fallback Mode: always save to database so it ends up in the JSON output file
            should_save = True
            if is_mongodb and cv_text and score is not None and score < 6:
                should_save = False

            try:
                if should_save:
                    is_new, saved_doc = db.save_job(job)
                    if is_new:
                        new_jobs_inserted += 1
                        print(f"  [NEW (Saved to DB)] {job.title} at {job.company} ({job.location}) -> Score: {score}/10")
                    else:
                        existing_jobs_updated += 1
                        print(f"  [MERGED (Saved to DB)] {job.title} at {job.company} ({job.location}) -> Score: {score}/10")
                    saved_jobs_list.append(saved_doc)
                else:
                    # Filtered out from MongoDB, but keep in our local list for JSON export
                    job_dict = job.to_dict()
                    print(f"  [Filtered (JSON Only)] {job.title} at {job.company} ({job.location}) -> Score: {score}/10 (Excluded from MongoDB)")
                    saved_jobs_list.append(job_dict)
            except Exception as e:
                print(f"  [Error] Failed to save job '{job.title}' to database: {e}")

    return verified_jobs_count, new_jobs_inserted, existing_jobs_updated, saved_jobs_list

def export_to_json(saved_jobs: List[dict], output_path: str):
    """Formats and writes output list to a JSON file with sequential serial numbers."""
    output_list = []
    for idx, doc in enumerate(saved_jobs, start=1):
        # Remove internal DB keys and add sequential serial number
        clean_doc = {k: v for k, v in doc.items() if k not in ("_id", "id", "dedup_key")}
        clean_doc = {"sr_no": idx, **clean_doc}
        output_list.append(clean_doc)

    try:
        with open(output_path, 'w', encoding='utf-8') as json_file:
            json.dump(output_list, json_file, indent=2, ensure_ascii=False)
        print(f"\nSuccessfully wrote {len(output_list)} distinct, verified jobs to '{output_path}'.")
    except Exception as e:
        print(f"Error writing to JSON output file: {e}")

def render_box_table(title: str, headers: List[str], col_widths: List[int], rows: List[List[str]], wrap_col_idx: int = -1):
    """Renders a sleek terminal table using Unicode box-drawing characters."""
    top_border = "┌─" + "─┬─".join(["─" * w for w in col_widths]) + "─┐"
    header_sep = "├─" + "─┼─".join(["─" * w for w in col_widths]) + "─┤"
    row_sep    = "├─" + "─┼─".join(["─" * w for w in col_widths]) + "─┤"
    bot_border = "└─" + "─┴─".join(["─" * w for w in col_widths]) + "─┘"
    format_str = "│ " + " │ ".join([f"{{:<{w}}}" for w in col_widths]) + " │"
    
    if title:
        print("\n" + title)
    print(top_border)
    print(format_str.format(*headers))
    print(header_sep)
    
    import textwrap
    for r_idx, row in enumerate(rows):
        if wrap_col_idx >= 0 and wrap_col_idx < len(row):
            wrap_text = str(row[wrap_col_idx])
            wrapped_lines = textwrap.wrap(wrap_text, width=col_widths[wrap_col_idx]) or [""]
            
            # First line
            first_row = list(row)
            first_row[wrap_col_idx] = wrapped_lines[0]
            print(format_str.format(*first_row))
            
            # Subsequent lines
            for extra_line in wrapped_lines[1:]:
                sub_row = [""] * len(row)
                sub_row[wrap_col_idx] = extra_line
                print(format_str.format(*sub_row))
        else:
            print(format_str.format(*row))
            
        if r_idx < len(rows) - 1:
            print(row_sep)
            
    print(bot_border + "\n")

def print_summary(total_scraped: int, verified_count: int, new_inserted: int, updated_count: int):
    """Prints execution stats summary."""
    print("\n" + "=" * 60)
    print("Execution Summary:")
    print(f"  - Total scraped: {total_scraped}")
    print(f"  - Total verified: {verified_count}")
    print(f"  - Newly inserted in MongoDB: {new_inserted}")
    print(f"  - Existing jobs updated/merged: {updated_count}")
    print("=" * 60)

def generate_documents_for_all_jobs(args, outputs_dir):
    try:
        from src.tailor_cv.generator import generate_tailored_documents
        with open(args.output, 'r', encoding='utf-8') as f:
            jobs_to_process = json.load(f)
        
        # Find recommended jobs (score > 6)
        def get_score_key(j):
            val = j.get("score")
            try:
                return int(val) if val is not None else 0
            except (ValueError, TypeError):
                return 0
                
        recommended = [j for j in jobs_to_process if get_score_key(j) > 6]
        recommended.sort(key=get_score_key, reverse=True)
        
        # Select top args.limit jobs to tailor
        target_tailor = recommended[:args.limit]
        
        resumes_dir = os.path.join(outputs_dir, "generated_resumes")
        os.makedirs(resumes_dir, exist_ok=True)
        
        print(f"\nTailoring documents for the top {len(target_tailor)} matching jobs (out of {len(jobs_to_process)} total verified)...")
        
        updated_jobs = []
        tailor_idx = 1
        generation_results = []
        
        for idx, job in enumerate(jobs_to_process, start=1):
            raw_title = job.get("title", "Unknown Title")
            title = " ".join(str(raw_title).replace("\n", " ").replace("\r", " ").split())
            raw_company = job.get("company", "Unknown Company")
            company = " ".join(str(raw_company).replace("\n", " ").replace("\r", " ").split())
            
            is_target = any(
                j.get("url") == job.get("url") and j.get("title") == job.get("title") 
                for j in target_tailor
            )
            
            status_str = "Pending"
            ats_str = "N/A"
            
            if is_target:
                from src.tailor_cv.generator import sanitize_filename
                comp_clean = sanitize_filename(company)
                tit_clean = sanitize_filename(title)
                target_folder = os.path.join(resumes_dir, f"{idx}_{comp_clean}_{tit_clean}")
                pdf_exists = os.path.exists(os.path.join(target_folder, "tailored_cv.pdf"))
                docx_exists = os.path.exists(os.path.join(target_folder, "tailored_cv.docx"))
                
                if pdf_exists and docx_exists and job.get("ats_score"):
                    print(f"\n[{tailor_idx}/{len(target_tailor)}] [Skipped Existing Documents] Documents already exist for '{title}' at '{company}'. Reusing to save API tokens.")
                    ats_score = job.get("ats_score")
                    ats_str = str(ats_score)
                    status_str = "Tailored (Cached)"
                    tailor_idx += 1
                else:
                    print(f"\n[{tailor_idx}/{len(target_tailor)}] Processing documents for '{title}' at '{company}'...")
                    if "sr_no" not in job or job["sr_no"] is None:
                        job["sr_no"] = idx
                    ats_score = generate_tailored_documents(
                        cv_path=args.cv,
                        job=job,
                        model=args.openrouter_model,
                        output_base_dir=resumes_dir
                    )

                    if ats_score:
                        job["ats_score"] = ats_score
                        ats_str = str(ats_score)
                        status_str = "Tailored"
                    else:
                        status_str = "Failed"
                    tailor_idx += 1
                    
                    if tailor_idx <= len(target_tailor):
                        import time
                        time.sleep(10.0)
            else:
                score_val = job.get("score")
                status_str = f"Skipped (Score {score_val}/10)"
            
            generation_results.append({
                "no": idx,
                "title": title,
                "company": company,
                "status": status_str,
                "ats_score": ats_str
            })
            updated_jobs.append(job)
                
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(updated_jobs, f, indent=2, ensure_ascii=False)
            
        headers = ["No", "Job Title", "Company", "Status", "ATS Score"]
        col_widths = [2, 22, 15, 15, 9]
        rows = []
        for res in generation_results:
            clean_title = " ".join(str(res['title']).replace("\n", " ").replace("\r", " ").split())
            clean_comp = " ".join(str(res['company']).replace("\n", " ").replace("\r", " ").split())
            t_title = clean_title[:20] + "..." if len(clean_title) > 22 else clean_title
            t_company = clean_comp[:13] + "..." if len(clean_comp) > 15 else clean_comp
            rows.append([str(res['no']), t_title, t_company, res['status'], res['ats_score']])
            
        render_box_table("GENERATING TAILORED CV AND COVER LETTER FOR EACH JOB POSTING", headers, col_widths, rows)
        
    except Exception as e:
        print(f"[Error] Failed to run document generation: {e}")


def print_match_scores_table(all_results, matched_results):
    headers = ["No", "Job Title", "Company", "Score"]
    col_widths = [4, 40, 25, 7]
    format_str = "| " + " | ".join([f"{{:<{w}}}" for w in col_widths]) + " |"
    sep_str = "|-" + "-|-".join(["-" * w for w in col_widths]) + "-|"
    
    print("\n" + "=" * 90)
    print("ALL JOB TITLES AND MATCH SCORES (0-10)")
    print("=" * 90)
    print(format_str.format(*headers))
    print(sep_str)
    for idx, res in enumerate(all_results, 1):
        clean_title = " ".join(str(res.get('title', '')).replace("\n", " ").replace("\r", " ").split())
        clean_comp = " ".join(str(res.get('company', '')).replace("\n", " ").replace("\r", " ").split())
        t_title = clean_title[:37] + "..." if len(clean_title) > 40 else clean_title
        t_company = clean_comp[:22] + "..." if len(clean_comp) > 25 else clean_comp
        score_str = f"{res['score']}/10" if res.get('score') is not None else "N/A"
        print(format_str.format(str(idx), t_title, t_company, score_str))
    print("-" * len(sep_str) + "\n")
    
    print("=" * 90)
    print("JOBS WITH MATCH SCORE > 6 (RECOMMENDED)")
    print("=" * 90)
    if not matched_results:
        print("No jobs with match score above 6.")
    else:
        for res in matched_results:
            clean_title = " ".join(str(res.get('title', '')).replace("\n", " ").replace("\r", " ").split())
            clean_comp = " ".join(str(res.get('company', '')).replace("\n", " ").replace("\r", " ").split())
            print(f"- {clean_title} ({clean_comp})")
    print("=" * 90 + "\n")

def print_jobs_table(output_path: str):
    """Prints separate formatted tables for LinkedIn and Glassdoor jobs."""
    if not os.path.exists(output_path):
        return
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        if not jobs:
            return
        
        # Group jobs by platform (case-insensitive)
        platform_jobs = {}
        for job in jobs:
            platform = job.get("site", "Unknown")
            if isinstance(platform, list):
                platform = platform[0] if platform else "Unknown"
            platform = str(platform).strip()
            platform_lower = platform.lower()
            if platform_lower not in platform_jobs:
                platform_jobs[platform_lower] = []
            platform_jobs[platform_lower].append(job)
            
        # Display order
        platform_order = ["linkedin", "glassdoor"]
        # Add other platforms if found
        for p in platform_jobs:
            if p not in platform_order:
                platform_order.append(p)
                
        for p_key in platform_order:
            if p_key not in platform_jobs or not platform_jobs[p_key]:
                continue
                
            jobs_list = platform_jobs[p_key]
            site_val = jobs_list[0].get("site", p_key.title())
            if isinstance(site_val, list):
                site_val = site_val[0] if site_val else p_key.title()
            platform_name = str(site_val).strip()
            
            # Filter to jobs with match score > 6
            recommended_list = []
            for job in jobs_list:
                score_val = job.get("score")
                try:
                    if score_val is not None and int(score_val) > 6:
                        recommended_list.append(job)
                except (ValueError, TypeError):
                    pass

            if not recommended_list:
                continue

            # Print Table Header
            title_text = f"{platform_name} Jobs (Match Score > 6)"
            border = "-" * max(30, len(title_text))
            print(f"\n{border}")
            print(title_text)
            print(border)
            
            headers = ["Sr No", "Job Role", "Company", "Location", "Experience", "Score", "Count In"]
            col_widths = {h: len(h) for h in headers}
            
            rows = []
            for idx, job in enumerate(recommended_list, start=1):
                raw_title = job.get("title", "")
                title = " ".join(str(raw_title).replace("\n", " ").replace("\r", " ").split())
                if len(title) > 30:
                    title = title[:27] + "..."
                    
                raw_company = job.get("company", "")
                company = " ".join(str(raw_company).replace("\n", " ").replace("\r", " ").split())
                if len(company) > 20:
                    company = company[:17] + "..."
                    
                raw_loc = job.get("location", "")
                location = " ".join(str(raw_loc).replace("\n", " ").replace("\r", " ").split())
                if len(location) > 15:
                    location = location[:12] + "..."
                    
                exp = job.get("experience_required")
                if exp is None:
                    exp = "N/A"
                exp = " ".join(str(exp).replace("\n", " ").replace("\r", " ").split())
                if len(exp) > 15:
                    exp = exp[:12] + "..."
                    
                score_val = job.get("score")
                score_str = f"{score_val}/10" if score_val is not None else "N/A"
                count_in = "✓"
                
                row = [str(idx), title, company, location, exp, score_str, count_in]
                rows.append(row)
                for i, val in enumerate(row):
                    h = headers[i]
                    col_widths[h] = max(col_widths[h], len(val))
                    
            render_box_table(
                title_text,
                headers,
                [col_widths[h] for h in headers],
                rows
            )

            
    except Exception as e:
        print(f"[Error] Failed to print summary table: {e}")


def normalize_job_dict(raw: dict) -> dict:
    """Normalizes non-standard JSON keys into standard job fields."""
    def get_val(keys, default=""):
        for k in keys:
            if k in raw and raw[k] is not None:
                val = str(raw[k]).strip()
                if val:
                    return val
        return default

    title = get_val(["title", "job_title", "role", "position", "jobRole", "job_name"], "Unknown Role")
    company = get_val(["company", "company_name", "employer", "org", "organization"], "Unknown Company")
    about_job = get_val(["about_job", "description", "job_description", "details", "summary", "jobSummary", "desc"], "")
    location = get_val(["location", "job_location", "city", "work_location", "place"], "N/A")
    experience = get_val(["experience_required", "experience", "exp", "years_of_experience", "req_exp"], "N/A")
    url = get_val(["url", "job_url", "link", "apply_url"], "")

    # Handle rich compensation structures
    comp = raw.get("compensation") or raw.get("salary")
    if isinstance(comp, dict):
        salary = comp.get("summary") or comp.get("pay") or comp.get("formatted") or str(comp)
    elif comp:
        salary = str(comp)
    else:
        salary = None

    # Handle list-based fields (responsibilities, must-have skills, requirements)
    details_parts = []
    if raw.get("responsibilities"):
        resp = raw["responsibilities"]
        if isinstance(resp, list):
            details_parts.append("Key Responsibilities:\n" + "\n".join(f"- {r}" for r in resp))
        elif isinstance(resp, str):
            details_parts.append(f"Key Responsibilities:\n{resp}")
            
    if raw.get("must_have_skills"):
        skills = raw["must_have_skills"]
        if isinstance(skills, list):
            details_parts.append("Must-Have Skills:\n" + ", ".join(skills))
        elif isinstance(skills, str):
            details_parts.append(f"Must-Have Skills:\n{skills}")
            
    if raw.get("requirements") or raw.get("qualifications"):
        reqs = raw.get("requirements") or raw.get("qualifications")
        if isinstance(reqs, list):
            details_parts.append("Requirements & Qualifications:\n" + "\n".join(f"- {r}" for r in reqs))
        elif isinstance(reqs, str):
            details_parts.append(f"Requirements & Qualifications:\n{reqs}")
            
    if details_parts:
        extra_text = "\n\n".join(details_parts)
        about_job = (about_job + "\n\n" + extra_text).strip() if about_job else extra_text

    if not about_job:
        about_job = f"Job Title: {title}. Company: {company}. Location: {location}."

    return {
        "title": title,
        "company": company,
        "about_job": about_job,
        "location": location,
        "experience_required": experience,
        "salary": salary,
        "url": url
    }

def fetch_manual_jobs_data(source: str) -> list:
    """Loads and parses JSON data from a URL or local file path."""
    source = source.strip()
    content = ""
    if source.startswith("http://") or source.startswith("https://"):
        import urllib.request
        print(f"\n[Manual Mode] Fetching JSON from URL: {source}...")
        req = urllib.request.Request(
            source,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
    else:
        local_path = os.path.abspath(source)
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Manual input JSON file not found at '{local_path}'.")
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()

    data = json.loads(content)
    
    # Handle dict with list property (e.g. {"jobs": [...]})
    if isinstance(data, dict):
        for k in ["jobs", "data", "postings", "results", "items"]:
            if k in data and isinstance(data[k], list):
                data = data[k]
                break
        if isinstance(data, dict):
            data = [data]

    if not isinstance(data, list):
        raise ValueError("JSON must contain an array of jobs or an object with a jobs list.")

    return [normalize_job_dict(item) for item in data if isinstance(item, dict)]

def run_manual_mode(args, outputs_dir: str):
    """Processes jobs from a manual JSON file or URL directly without scraping, generating ATS scores, PDF, Word, and LaTeX documents."""
    try:
        manual_jobs = fetch_manual_jobs_data(args.manual)
    except Exception as e:
        print(f"[Error] Failed to load manual JSON data: {e}")
        return
        
    if not manual_jobs:
        print("[Error] No valid jobs found in input.")
        return
        
    print("\n" + "=" * 60)
    print(f"Running Manual Mode for {len(manual_jobs)} Jobs from: {args.manual}")
    print(f"CV: {args.cv}")
    print("=" * 60)
    
    # 1. Extract CV Text
    from src.tailor_cv.pdf_parser import extract_text_from_pdf
    try:
        cv_text = extract_text_from_pdf(args.cv)
    except Exception as e:
        print(f"[Error] Failed to read CV PDF: {e}")
        return
        
    # 2. Score All Jobs Against CV
    from src.tailor_cv.claude_client import get_llm_client
    client = get_llm_client(model=args.groq_model)
    
    print("\n[ATS Matching] Evaluating alignment for each job posting against your CV...")
    for idx, job in enumerate(manual_jobs, 1):
        print(f"  [{idx}/{len(manual_jobs)}] Scoring '{job['title']}' at '{job['company']}'...")
        try:
            res = client.get_match_score(cv_text, job)
            job["score"] = res.get("score", 0)
            job["explanation"] = res.get("explanation", "No explanation provided.")
        except Exception as e:
            print(f"    -> Scoring error: {e}")
            job["score"] = 0
            job["explanation"] = f"Scoring error: {e}"
        import time
        time.sleep(2.0)
        
    # 3. Categorize Aligned vs Non-Aligned
    aligned_jobs = [j for j in manual_jobs if (j.get("score") or 0) > 6]
    non_aligned_jobs = [j for j in manual_jobs if (j.get("score") or 0) <= 6]
    
    # 4. Display Non-Aligned Jobs Table with Explanations
    if non_aligned_jobs:
        headers_na = ["No", "Role", "Company", "Score", "Why Not Aligned"]
        col_widths_na = [2, 17, 13, 5, 33]
        rows_na = []
        for idx, j in enumerate(non_aligned_jobs, 1):
            t = j['title'][:14] + "..." if len(j['title']) > 17 else j['title']
            c = j['company'][:10] + "..." if len(j['company']) > 13 else j['company']
            s = f"{j.get('score', 0)}/10"
            exp = " ".join(j.get('explanation', '').replace("\n", " ").split())
            rows_na.append([str(idx), t, c, s, exp])
            
        render_box_table(
            "NON-ALIGNED JOBS (MATCH SCORE <= 6)",
            headers_na,
            col_widths_na,
            rows_na,
            wrap_col_idx=4
        )
        
    # 5. Display Aligned Jobs
    if aligned_jobs:
        headers_a = ["No", "Role", "Company", "Score"]
        col_widths_a = [2, 22, 15, 6]
        rows_a = []
        for idx, j in enumerate(aligned_jobs, 1):
            t = j['title'][:19] + "..." if len(j['title']) > 22 else j['title']
            c = j['company'][:12] + "..." if len(j['company']) > 15 else j['company']
            s = f"{j.get('score', 0)}/10"
            rows_a.append([str(idx), t, c, s])
            
        render_box_table(
            "ALIGNED JOBS (RECOMMENDED: MATCH SCORE > 6)",
            headers_a,
            col_widths_a,
            rows_a
        )
        
    # 6. Interactive User Choice for Document Generation Scope
    target_jobs = aligned_jobs
    if non_aligned_jobs and aligned_jobs:
        print("Choose document generation scope:")
        print("  [1] Aligned Only (Recommended — Generate only for Score > 6 jobs)")
        print("  [2] All Jobs (Generate for both Aligned and Non-Aligned jobs)")
        try:
            choice = input("\nEnter your choice [1 or 2, default is 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"
        if choice == "2":
            target_jobs = manual_jobs
            print(f"\n[Scope Selected] Proceeding with ALL {len(target_jobs)} jobs.")
        else:
            target_jobs = aligned_jobs
            print(f"\n[Scope Selected] Proceeding with {len(target_jobs)} Aligned jobs only.")
    elif not aligned_jobs:
        print("\n[Notice] No jobs met the alignment threshold (Score > 6).")
        try:
            choice = input("Do you still want to generate documents for all jobs? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"
        if choice in ("y", "yes"):
            target_jobs = manual_jobs
            print(f"\n[Scope Selected] Proceeding with {len(target_jobs)} jobs.")
        else:
            print("No documents generated. Exiting.")
            return

    # 7. Document Generation (PDF, Word, LaTeX)
    from src.tailor_cv.generator import generate_tailored_documents
    resumes_dir = os.path.join(outputs_dir, "generated_resumes")
    os.makedirs(resumes_dir, exist_ok=True)
    
    generation_results = []
    print(f"\nTailoring CV, Cover Letter & LaTeX Resume for {len(target_jobs)} target jobs...")
    for idx, job in enumerate(target_jobs, start=1):
        raw_title = job.get("title", "Unknown Title")
        title = " ".join(str(raw_title).replace("\n", " ").replace("\r", " ").split())
        raw_company = job.get("company", "Unknown Company")
        company = " ".join(str(raw_company).replace("\n", " ").replace("\r", " ").split())
        
        job["sr_no"] = idx
        print(f"\n[{idx}/{len(target_jobs)}] Generating Tailored Documents for '{title}' at '{company}'...")
        ats_score = generate_tailored_documents(
            cv_path=args.cv,
            job=job,
            model=args.openrouter_model,
            output_base_dir=resumes_dir
        )
        
        status_str = "Tailored" if ats_score else "Failed"
        ats_str = str(ats_score) if ats_score else "N/A"
        generation_results.append({
            "no": idx,
            "title": title,
            "company": company,
            "status": status_str,
            "ats_score": ats_str
        })
        
        if idx < len(target_jobs):
            import time
            time.sleep(3.0)
            
    headers = ["No", "Job Title", "Company", "Status", "ATS Score"]
    col_widths = [2, 22, 15, 15, 9]
    rows_res = []
    for res in generation_results:
        clean_title = " ".join(str(res['title']).replace("\n", " ").replace("\r", " ").split())
        clean_comp = " ".join(str(res['company']).replace("\n", " ").replace("\r", " ").split())
        t_title = clean_title[:19] + "..." if len(clean_title) > 22 else clean_title
        t_company = clean_comp[:12] + "..." if len(clean_comp) > 15 else clean_comp
        rows_res.append([str(res['no']), t_title, t_company, res['status'], res['ats_score']])
        
    render_box_table("MANUAL JOBS: GENERATED TAILORED CV, COVER LETTER & LATEX RESUME", headers, col_widths, rows_res)


def main():
    args = parse_args()

    # Resolve data folder at project's root location
    project_root = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(project_root, "data")
    os.makedirs(outputs_dir, exist_ok=True)

    # Verify environment variables
    from src.config import Config
    
    # Check active API key (Claude or Google based on API_KEY in .env)
    active_provider = Config.get_active_provider()
    active_key = Config.get_active_api_key()
    if not active_key or not active_key.strip():
        print(f"[ERROR] Active provider is '{active_provider}' but its API key is not set in .env. Execution stopped.")
        return
    print(f"[Config] Active LLM Provider: {active_provider.upper()}")
        
    # Restrict limit to 25 and warn if it is higher
    if args.limit > 25:
        print("\n" + "=" * 60)
        print("[Warning] Maximum limit is 25 only. Adjusting limit to 25.")
        print("=" * 60 + "\n")
        args.limit = 25

    # Resolve Output Path to be inside the data directory
    args.output = os.path.abspath(args.output) if args.output else os.path.join(outputs_dir, "scraped_jobs.json")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # 2. Resolve CV Path (Bug 2)
    cv_text = ""
    if not args.cv and Config.CV_PATH:
        args.cv = Config.CV_PATH

    if not args.cv:
        # Prompt user and wait until a valid CV path is provided
        while True:
            user_cv = input("Please enter the path to your CV PDF file (required): ").strip().strip("'\"")
            if not user_cv:
                print("CV path cannot be empty. Please provide a path.")
                continue
            resolved_cv = os.path.abspath(user_cv)
            if os.path.exists(resolved_cv) and os.path.isfile(resolved_cv):
                args.cv = resolved_cv
                break
            else:
                print(f"CV file not found at '{resolved_cv}'. Please enter a valid path.")
    else:
        # Verify if explicitly provided CV exists. If not, prompt and wait until a valid path is given
        clean_cv = args.cv.strip().strip("'\"")
        resolved_cv = os.path.abspath(clean_cv)
        if not (os.path.exists(resolved_cv) and os.path.isfile(resolved_cv)):
            print(f"Specified CV file not found at '{resolved_cv}'.")
            while True:
                user_cv = input("Please enter the path to your CV PDF file (required): ").strip().strip("'\"")
                if not user_cv:
                    print("CV path cannot be empty. Please provide a path.")
                    continue
                resolved_cv = os.path.abspath(user_cv)
                if os.path.exists(resolved_cv) and os.path.isfile(resolved_cv):
                    args.cv = resolved_cv
                    break
                else:
                    print(f"CV file not found at '{resolved_cv}'. Please enter a valid path.")
        else:
            args.cv = resolved_cv


    # Extract CV text (since we guaranteed the CV file exists and is valid)
    try:
        from src.tailor_cv.pdf_parser import extract_text_from_pdf
        cv_text = extract_text_from_pdf(args.cv)
    except Exception as e:
        print(f"[Error] Failed to extract text from CV: {e}")
    
    # 3. Check if we should run manual input mode directly
    if args.manual:
        run_manual_mode(args, outputs_dir)
        return

    # 4. Check if we should only run CV matching on existing scraped_jobs.json
    if args.match_only:
        print("=" * 60)
        print("Running CV Matching Mode Only")
        print(f"CV: {args.cv}")
        print(f"Jobs Source: {args.output}")
        print("=" * 60)
        
        if not args.cv or not os.path.exists(args.cv):
            print(f"[Error] CV file not found at '{args.cv}'. Please place your CV PDF in the root directory or specify its path with --cv.")
            return
        
        if not os.path.exists(args.output):
            print(f"[Error] Scraped jobs file not found at '{args.output}'. Please run scraping first or verify the path.")
            return
            
        try:
            all_results, matched_results = run_cv_matching(
                cv_path=args.cv,
                jobs_json_path=args.output,
                model=args.groq_model
            )
            
            print_jobs_table(args.output)
            generate_documents_for_all_jobs(args, outputs_dir)
            
        except Exception as e:
            print(f"[Error] CV matching failed: {e}")
        return


    # 2. Otherwise run scraping as normal
    print("=" * 60)
    print(f"Starting Job Scraper Engine (LangGraph)")
    print(f"Role: {args.role}")
    print(f"Location: {args.location}")
    print(f"Experience Criteria: {args.experience}")
    print(f"Total limit: {args.limit}")
    print("=" * 60)

    # Dynamically discover scrapers (OCP) and filter based on user selection
    selected_sources = [s.strip().lower() for s in args.sources.split(",")]
    scraper_classes = [
        cls for cls in get_scrapers()
        if cls.__name__.lower().replace("scraper", "") in selected_sources
    ]
    
    # Check if LinkedInScraper is being run, and if so, check login
    has_linkedin = any(cls.__name__ == "LinkedInScraper" for cls in scraper_classes)
    if has_linkedin:
        try:
            from linkedin_login import check_and_login
            check_and_login()
        except Exception as e:
            print(f"[Warning] LinkedIn login helper failed to run: {e}")
            
    # Check if GlassdoorScraper is being run, and if so, check login
    has_glassdoor = any(cls.__name__ == "GlassdoorScraper" for cls in scraper_classes)
    if has_glassdoor:
        try:
            from glassdoor_login import check_and_login_glassdoor
            check_and_login_glassdoor()
        except Exception as e:
            print(f"[Warning] Glassdoor login helper failed to run: {e}")
            
        # Verify Glassdoor credentials
        if not Config.GLASSDOOR_COOKIE or not Config.GLASSDOOR_COOKIE.strip() or not Config.GLASSDOOR_USER_AGENT or not Config.GLASSDOOR_USER_AGENT.strip():
            print("[ERROR] GLASSDOOR_COOKIE or GLASSDOOR_USER_AGENT is not set in .env. Glassdoor execution stopped.")
            return

    # Build and invoke LangGraph Scraper Graph
    print("\n[Pipeline] Building and running LangGraph pipeline...")
    scraper_graph = build_scraper_graph()
    
    all_processed_jobs = []
    seen_job_urls = set()
    start_offset = 0
    iteration = 1
    max_iterations = 6  # Safety limit to prevent infinite loops
    
    total_limit = args.limit or 15
    total_raw_scraped = 0
    total_new_inserted = 0
    total_updated_count = 0

    while len(all_processed_jobs) < total_limit and iteration <= max_iterations:
        print(f"\n" + "=" * 60)
        print(f"Scraping Iteration {iteration} (Start Offset: {start_offset})")
        print(f"Current Verified Jobs Count: {len(all_processed_jobs)} / {total_limit}")
        print("=" * 60)
        
        initial_state = {
            "role": args.role,
            "location": args.location,
            "experience": args.experience,
            "limit": total_limit,
            "groq_model": args.groq_model,
            "cv_text": cv_text,
            "sources": selected_sources,
            "output_path": args.output,
            "raw_jobs": [],
            "start_offset": start_offset
        }
        
        try:
            graph_result = scraper_graph.invoke(initial_state)
            
            # Collect jobs from this run
            new_jobs = graph_result.get("processed_jobs_list", [])
            stats = graph_result.get("summary_stats", {})
            
            total_raw_scraped += stats.get("total_raw", 0)
            total_new_inserted += stats.get("new_inserted", 0)
            total_updated_count += stats.get("updated", 0)
            
            added_this_run = 0
            for job in new_jobs:
                url = job.get("url")
                if url and url not in seen_job_urls:
                    seen_job_urls.add(url)
                    all_processed_jobs.append(job)
                    added_this_run += 1
                    
            print(f"\n[Pipeline] Iteration {iteration} finished. Added {added_this_run} new verified jobs.")
            print(f"[Pipeline] Current total verified jobs: {len(all_processed_jobs)} / {total_limit}")
            
            if len(all_processed_jobs) >= total_limit:
                break
                
            if stats.get("total_raw", 0) == 0 and added_this_run == 0:
                print("[Pipeline] No more raw jobs found from sources. Stopping scraper loop.")
                break
                
            # If we didn't add any new verified jobs, advance start_offset to get next batch of results
            start_offset += max(stats.get("total_raw", 0), 15)
            
        except Exception as graph_err:
            print(f"[Error] Scraper iteration failed: {graph_err}")
            break
            
        iteration += 1

    # Keep only recommended jobs (score > 6) if CV was provided
    if cv_text:
        processed_jobs = [
            j for j in all_processed_jobs 
            if (j.get("score") is not None and int(j.get("score")) > 6)
        ]
    else:
        processed_jobs = all_processed_jobs
    
    print_summary(total_raw_scraped, len(processed_jobs), total_new_inserted, total_updated_count)
    
    # Export to output JSON file (only score > 6)
    export_to_json(processed_jobs, args.output)


    # Match CV
    if os.path.exists(args.cv):
        try:
            all_results, matched_results = run_cv_matching(
                cv_path=args.cv,
                jobs_json_path=args.output,
                model=args.groq_model
            )
            
            print_jobs_table(args.output)
            generate_documents_for_all_jobs(args, outputs_dir)
            
        except Exception as e:
            print(f"[Error] CV matching failed: {e}")
    else:
        print(f"\n[CV Matcher Info] CV file '{args.cv}' not found. Skipping CV matching.")
        print("To run CV matching, please place your CV PDF file in the root folder (default name: cv.pdf) or specify the path via --cv.")
        print_jobs_table(args.output)


if __name__ == "__main__":
    main()
