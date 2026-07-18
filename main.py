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
    parser = argparse.ArgumentParser(description="SOLID Job Scraper for LinkedIn, Glassdoor, and Indeed")
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
    parser.add_argument("--sources", type=str, default="linkedin,glassdoor,indeed", help="Comma-separated list of job sources to scrape (default: 'linkedin,glassdoor,indeed')")
    
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
        from src.tailor_cv.claude_client import ClaudeClient
        client = ClaudeClient(model=args.groq_model)

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
        
        print(f"\nTailoring documents for the top {len(target_tailor)} matching jobs (out of {len(jobs_to_process)} total verified)...")
        
        updated_jobs = []
        tailor_idx = 1
        generation_results = []
        
        for idx, job in enumerate(jobs_to_process, start=1):
            title = job.get("title", "Unknown Title")
            company = job.get("company", "Unknown Company")
            
            is_target = any(
                j.get("url") == job.get("url") and j.get("title") == job.get("title") 
                for j in target_tailor
            )
            
            status_str = "Pending"
            ats_str = "N/A"
            
            if is_target:
                print(f"\n[{tailor_idx}/{len(target_tailor)}] Processing documents for '{title}' at '{company}'...")
                ats_score = generate_tailored_documents(
                    cv_path=args.cv,
                    job=job,
                    model=args.openrouter_model,
                    output_base_dir=outputs_dir
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
        col_widths = [4, 35, 20, 22, 11]
        format_str = "| " + " | ".join([f"{{:<{w}}}" for w in col_widths]) + " |"
        sep_str = "|-" + "-|-".join(["-" * w for w in col_widths]) + "-|"
        
        print("\n" + "=" * 90)
        print("GENERATING TAILORED CV AND COVER LETTER FOR EACH JOB POSTING")
        print("=" * 90)
        print(format_str.format(*headers))
        print(sep_str)
        for res in generation_results:
            t_title = res['title'][:32] + "..." if len(res['title']) > 35 else res['title']
            t_company = res['company'][:17] + "..." if len(res['company']) > 20 else res['company']
            print(format_str.format(str(res['no']), t_title, t_company, res['status'], res['ats_score']))
        print("-" * len(sep_str) + "\n")
        
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
        t_title = res['title'][:37] + "..." if len(res['title']) > 40 else res['title']
        t_company = res['company'][:22] + "..." if len(res['company']) > 25 else res['company']
        score_str = f"{res['score']}/10" if res['score'] is not None else "N/A"
        print(format_str.format(str(idx), t_title, t_company, score_str))
    print("-" * len(sep_str) + "\n")
    
    print("=" * 90)
    print("JOBS WITH MATCH SCORE > 6 (RECOMMENDED)")
    print("=" * 90)
    if not matched_results:
        print("No jobs with match score above 6.")
    else:
        for res in matched_results:
            print(f"- {res['title']} ({res['company']})")
    print("=" * 90 + "\n")

def print_jobs_table(output_path: str):
    """Prints separate formatted tables for LinkedIn, Glassdoor, and Indeed jobs."""
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
            platform = job.get("site", "Unknown").strip()
            platform_lower = platform.lower()
            if platform_lower not in platform_jobs:
                platform_jobs[platform_lower] = []
            platform_jobs[platform_lower].append(job)
            
        # Display order
        platform_order = ["linkedin", "glassdoor", "indeed"]
        # Add other platforms if found
        for p in platform_jobs:
            if p not in platform_order:
                platform_order.append(p)
                
        for p_key in platform_order:
            if p_key not in platform_jobs or not platform_jobs[p_key]:
                continue
                
            jobs_list = platform_jobs[p_key]
            platform_name = jobs_list[0].get("site", p_key.title()).strip()
            
            # Print Table Header
            title_text = f"{platform_name} Jobs"
            border = "-" * max(30, len(title_text))
            print(f"\n{border}")
            print(title_text)
            print(border)
            
            headers = ["Sr No", "Job Role", "Company", "Location", "Experience", "Score", "Count In"]
            col_widths = {h: len(h) for h in headers}
            
            rows = []
            for idx, job in enumerate(jobs_list, start=1):
                title = job.get("title", "").replace("\n", " ").replace("\r", " ").strip()
                if len(title) > 30:
                    title = title[:27] + "..."
                    
                company = job.get("company", "").strip()
                if len(company) > 20:
                    company = company[:17] + "..."
                    
                location = job.get("location", "").strip()
                if len(location) > 15:
                    location = location[:12] + "..."
                    
                exp = job.get("experience_required")
                if exp is None:
                    exp = "N/A"
                exp = str(exp).strip()
                if len(exp) > 15:
                    exp = exp[:12] + "..."
                    
                score_val = job.get("score")
                score_str = f"{score_val}/10" if score_val is not None else "N/A"
                
                try:
                    is_above_6 = score_val is not None and int(score_val) > 6
                except (ValueError, TypeError):
                    is_above_6 = False
                    
                count_in = "✓" if is_above_6 else ""
                
                row = [str(idx), title, company, location, exp, score_str, count_in]
                rows.append(row)
                for i, val in enumerate(row):
                    h = headers[i]
                    col_widths[h] = max(col_widths[h], len(val))
                    
            # Build formatting strings for a nice table
            format_str = "| " + " | ".join([f"{{:<{col_widths[h]}}}" for h in headers]) + " |"
            sep_str = "|-" + "-|-".join(["-" * col_widths[h] for h in headers]) + "-|"
            
            print(format_str.format(*headers))
            print(sep_str)
            for row in rows:
                print(format_str.format(*row))
            print("-" * len(sep_str) + "\n")
            
    except Exception as e:
        print(f"[Error] Failed to print summary table: {e}")


def main():
    # Verify environment variables
    from src.config import Config
    
    # Check Claude API
    if not Config.CLAUDE_API or not Config.CLAUDE_API.strip():
        print("[ERROR] CLAUDE_API is not set in the .env file. Execution stopped.")
        return
        
    args = parse_args()
    
    # Restrict limit to 25 and warn if it is higher
    if args.limit > 25:
        print("\n" + "=" * 60)
        print("[Warning] Maximum limit is 25 only. Adjusting limit to 25.")
        print("=" * 60 + "\n")
        args.limit = 25
        
    # Resolve outputs folder at project's root location
    project_root = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(project_root, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    # Resolve Output Path to be inside the outputs directory
    args.output = os.path.abspath(args.output) if args.output else os.path.join(outputs_dir, "scraped_jobs.json")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # 2. Resolve CV Path (Bug 2)
    cv_text = ""
    if not args.cv:
        # Prompt user and wait until a valid CV path is provided
        while True:
            user_cv = input("Please enter the path to your CV PDF file (required): ").strip()
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
        resolved_cv = os.path.abspath(args.cv)
        if not (os.path.exists(resolved_cv) and os.path.isfile(resolved_cv)):
            print(f"Specified CV file not found at '{resolved_cv}'.")
            while True:
                user_cv = input("Please enter the path to your CV PDF file (required): ").strip()
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
    
    # 3. Check if we should only run CV matching on existing scraped_jobs.json
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
            
            print_match_scores_table(all_results, matched_results)
            
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

    # Check if IndeedScraper is being run, and if so, check login
    has_indeed = any(cls.__name__ == "IndeedScraper" for cls in scraper_classes)
    if has_indeed:
        try:
            from indeed_login import check_and_login_indeed
            check_and_login_indeed()
        except Exception as e:
            print(f"[Warning] Indeed login helper failed to run: {e}")

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

    # Keep all scraped and verified jobs instead of slicing by limit
    processed_jobs = all_processed_jobs
    
    print_summary(total_raw_scraped, len(processed_jobs), total_new_inserted, total_updated_count)
    
    # Export to output JSON file
    export_to_json(processed_jobs, args.output)


    # Match CV
    if os.path.exists(args.cv):
        try:
            all_results, matched_results = run_cv_matching(
                cv_path=args.cv,
                jobs_json_path=args.output,
                model=args.groq_model
            )
            
            print_match_scores_table(all_results, matched_results)
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
