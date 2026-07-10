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
    parser.add_argument("--groq-model", type=str, default="llama-3.1-8b-instant", help="Groq model to use for scoring")
    parser.add_argument("--sources", type=str, default="linkedin,glassdoor,indeed", help="Comma-separated list of job sources to scrape (default: 'linkedin,glassdoor,indeed')")
    return parser.parse_args()

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

    # Instantiate GroqClient if matching is requested
    client = None
    if cv_text:
        from src.tailor_cv.groq_client import GroqClient
        client = GroqClient(model=args.groq_model)

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
                
                # Respect rate limit between Groq API calls (30 RPM safe)
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
    print("\n" + "=" * 60)
    print("GENERATING TAILORED CV AND COVER LETTER FOR EACH JOB POSTING...")
    print("=" * 60)
    try:
        from src.tailor_cv.generator import generate_tailored_documents
        with open(args.output, 'r', encoding='utf-8') as f:
            jobs_to_process = json.load(f)
        
        updated_jobs = []
        for idx, job in enumerate(jobs_to_process, 1):
            title = job.get("title", "Unknown Title")
            company = job.get("company", "Unknown Company")
            print(f"[{idx}/{len(jobs_to_process)}] Processing documents for '{title}' at '{company}'...")
            ats_score = generate_tailored_documents(
                cv_path=args.cv,
                job=job,
                model=args.groq_model,
                output_base_dir=outputs_dir
            )
            if ats_score:
                job["ats_score"] = ats_score
            updated_jobs.append(job)
            
            if idx < len(jobs_to_process):
                import time
                time.sleep(10.0)
                
        # Write updated jobs back to the local database file
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(updated_jobs, f, indent=2, ensure_ascii=False)
            
        print("=" * 60)
        print("Document generation complete and updated main JSON database.")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"[Error] Failed to run document generation: {e}")

def main():
    # Verify environment variables
    from src.config import Config
    
    # 1. Check Groq API
    if not Config.GROQ_API or not Config.GROQ_API.strip():
        print("[ERROR] GROQ_API is not set in the .env file. Execution stopped.")
        return
    args = parse_args()
    
    # Restrict limit to 25 and warn if it is higher
    if args.limit > 25:
        print("\n" + "=" * 60)
        print("[Warning] Maximum limit is 25 only. Adjusting limit to 25.")
        print("=" * 60 + "\n")
        args.limit = 25
        
    # Resolve outputs folder dynamically from execution directory (CWD)
    outputs_dir = None
    if not args.output_dir:
        try:
            user_outputs_dir = input("Enter directory path to save all outputs (default: ./outputs): ").strip()
            if not user_outputs_dir:
                outputs_dir = os.path.abspath("outputs")
            else:
                outputs_dir = os.path.abspath(user_outputs_dir)
        except EOFError:
            outputs_dir = os.path.abspath("outputs")
    else:
        outputs_dir = os.path.abspath(args.output_dir)
    os.makedirs(outputs_dir, exist_ok=True)

    # 1. Resolve Output Path (Bug 1)
    if not args.output:
        default_output_path = os.path.join(outputs_dir, "scraped_jobs.json")
        try:
            user_output = input(f"Enter path to save the output JSON file (default: {default_output_path}): ").strip()
            if not user_output:
                args.output = default_output_path
            else:
                if not os.path.dirname(user_output):
                    args.output = os.path.join(outputs_dir, user_output)
                else:
                    args.output = os.path.abspath(user_output)
        except EOFError:
            args.output = default_output_path
    else:
        if not os.path.dirname(args.output):
            args.output = os.path.join(outputs_dir, args.output)
        else:
            args.output = os.path.abspath(args.output)
    
    # Ensure parent directory of output JSON exists
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
        print(f"\n[CV Matcher] Extracting text from CV: {args.cv}...")
        cv_text = extract_text_from_pdf(args.cv)
        print(f"[CV Matcher] Extracted {len(cv_text)} characters from CV.")
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
            
            # Print general/all scores
            print("\n" + "=" * 60)
            print("ALL JOB TITLES AND MATCH SCORES (0-10):")
            print("=" * 60)
            for res in all_results:
                print(f"- {res['title']} ({res['company']}) - Score: {res['score']}/10")
                print(f"  Explanation: {res['explanation']}")
            
            # Print match score > 6
            print("\n" + "=" * 60)
            print("JOBS WITH MATCH SCORE > 6 (RECOMMENDED):")
            print("=" * 60)
            if not matched_results:
                print("No jobs with match score above 6.")
            else:
                for res in matched_results:
                    print(f"- {res['title']}")
            print("=" * 60 + "\n")
            
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
    initial_state = {
        "role": args.role,
        "location": args.location,
        "experience": args.experience,
        "limit": args.limit,
        "groq_model": args.groq_model,
        "cv_text": cv_text,
        "sources": selected_sources,
        "output_path": args.output,
        "raw_jobs": []
    }
    
    graph_result = scraper_graph.invoke(initial_state)
    
    # Process summary and save outputs
    stats = graph_result.get("summary_stats", {})
    total_raw_scraped = stats.get("total_raw", 0)
    verified_jobs_count = stats.get("total_verified", 0)
    total_new_inserted = stats.get("new_inserted", 0)
    total_updated_count = stats.get("updated", 0)
    
    print_summary(total_raw_scraped, verified_jobs_count, total_new_inserted, total_updated_count)
    
    # Export to output JSON file
    processed_jobs = graph_result.get("processed_jobs_list", [])
    export_to_json(processed_jobs, args.output)


    # Match CV
    if os.path.exists(args.cv):
        try:
            all_results, matched_results = run_cv_matching(
                cv_path=args.cv,
                jobs_json_path=args.output,
                model=args.groq_model
            )
            
            # Print general/all scores
            print("\n" + "=" * 60)
            print("ALL JOB TITLES AND MATCH SCORES (0-10):")
            print("=" * 60)
            for res in all_results:
                print(f"- {res['title']} ({res['company']}) - Score: {res['score']}/10")
                print(f"  Explanation: {res['explanation']}")
            
            # Print match score > 6
            print("\n" + "=" * 60)
            print("JOBS WITH MATCH SCORE > 6 (RECOMMENDED):")
            print("=" * 60)
            if not matched_results:
                print("No jobs with match score above 6.")
            else:
                for res in matched_results:
                    print(f"- {res['title']}")
            print("=" * 60 + "\n")
            
            generate_documents_for_all_jobs(args, outputs_dir)
            
        except Exception as e:
            print(f"[Error] CV matching failed: {e}")
    else:
        print(f"\n[CV Matcher Info] CV file '{args.cv}' not found. Skipping CV matching.")
        print("To run CV matching, please place your CV PDF file in the root folder (default name: cv.pdf) or specify the path via --cv.")

if __name__ == "__main__":
    main()
