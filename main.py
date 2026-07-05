import argparse
import json
import os
from typing import List, Tuple
from src.config import Config
from src.database import DatabaseHandler, LocalDatabaseHandler
from src.interfaces import DatabaseInterface
from src.verifier import JobVerifier
from src.scrapers import get_scrapers
from src.models import Job
from cv_matcher.matcher import run_cv_matching

def parse_args():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="SOLID Job Scraper for LinkedIn, Glassdoor, and Indeed")
    parser.add_argument("--role", type=str, default="Software QA Engineer", help="Job role to search for")
    parser.add_argument("--location", type=str, default="Pune", help="Location to search for")
    parser.add_argument("--experience", type=str, default="1-3 years", help="Required experience level (e.g., '1-3 years', 'Entry Level')")
    parser.add_argument("--output", type=str, default="scraped_jobs.json", help="Path to save the JSON output file")
    parser.add_argument("--limit", type=int, default=15, help="Total max jobs to scrape across all sources (default: 15)")
    parser.add_argument("--cv", type=str, default="cv.pdf", help="Path to your CV PDF file")
    parser.add_argument("--match-only", action="store_true", help="Only run CV matching on existing scraped jobs json file")
    parser.add_argument("--skip-matching", action="store_true", help="Skip matching jobs with CV using LLM")
    parser.add_argument("--groq-model", type=str, default="llama-3.1-8b-instant", help="Groq model to use for scoring")
    return parser.parse_args()

def execute_scraping(scrapers: list, args) -> List[Job]:
    """Runs all discovered scrapers and collects raw jobs."""
    all_scraped_jobs = []
    remaining_limit = args.limit
    for scraper_cls in scrapers:
        if remaining_limit <= 0:
            print(f"\n[Scraping] Total limit of {args.limit} jobs reached. Skipping remaining scrapers.")
            break
        try:
            scraper = scraper_cls()
            scraper_name = scraper.__class__.__name__
            print(f"\n[Scraping] Launching {scraper_name}...")
            jobs = scraper.scrape(args.role, args.location, args.experience, limit=remaining_limit)
            print(f"[Scraping] {scraper_name} returned {len(jobs)} jobs.")
            all_scraped_jobs.extend(jobs)
            remaining_limit -= len(jobs)
        except Exception as e:
            scraper_name = scraper_cls.__name__
            print(f"[Error] Scraper {scraper_name} failed: {e}")
    return all_scraped_jobs[:args.limit]

def process_and_save_jobs(db: DatabaseInterface, verifier: JobVerifier, raw_jobs: List[Job], args) -> Tuple[int, int, int, List[dict]]:
    """Filters, verifies, and saves scraped jobs to database."""
    verified_jobs_count = 0
    new_jobs_inserted = 0
    existing_jobs_updated = 0
    saved_jobs_list = []

    print("\n[Verifying & Saving] Processing jobs...")
    for job in raw_jobs:
        if verifier.verify(job, args.role, args.location, args.experience):
            verified_jobs_count += 1
            try:
                is_new, saved_doc = db.save_job(job)
                if is_new:
                    new_jobs_inserted += 1
                    print(f"  [NEW] {job.title} at {job.company} ({job.location}) from {job.site}")
                else:
                    existing_jobs_updated += 1
                    print(f"  [MERGED] {job.title} at {job.company} ({job.location}) -> Sites: {saved_doc['site']}")
                
                saved_jobs_list.append(saved_doc)
            except Exception as e:
                print(f"  [Error] Failed to save job '{job.title}' to MongoDB: {e}")

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

def main():
    args = parse_args()
    
    # Restrict limit to 25 and warn if it is higher
    if args.limit > 25:
        print("\n" + "=" * 60)
        print("[Warning] Maximum limit is 25 only. Adjusting limit to 25.")
        print("=" * 60 + "\n")
        args.limit = 25
    
    # 1. Check if we should only run CV matching on existing scraped_jobs.json
    if args.match_only:
        print("=" * 60)
        print("Running CV Matching Mode Only")
        print(f"CV: {args.cv}")
        print(f"Jobs Source: {args.output}")
        print("=" * 60)
        
        if not os.path.exists(args.cv):
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
            
        except Exception as e:
            print(f"[Error] CV matching failed: {e}")
        return

    # 2. Otherwise run scraping as normal
    print("=" * 60)
    print(f"Starting Job Scraper Engine")
    print(f"Role: {args.role}")
    print(f"Location: {args.location}")
    print(f"Experience Criteria: {args.experience}")
    print(f"Total limit: {args.limit}")
    print("=" * 60)

    # Initialize Database using Constructor-based Dependency Injection
    db = None
    if Config.MONGO_URI and Config.MONGO_URI.strip():
        try:
            print("Connecting to MongoDB...")
            db = DatabaseHandler(
                uri=Config.MONGO_URI,
                db_name=Config.DB_NAME,
                collection_name=Config.COLLECTION_NAME
            )
            print("Connected to MongoDB successfully.")
        except Exception as e:
            print(f"[Warning] MongoDB connection failed ({e})")
            print("Please check your MONGO_URI in .env if you want to write to MongoDB.")
    
    if db is None:
        print("Falling back to local in-memory storage (results will be verified, deduplicated, and saved to the JSON output file).")
        db = LocalDatabaseHandler()

    # Instantiate verifier
    verifier = JobVerifier()
    
    # Dynamically discover scrapers (OCP)
    scraper_classes = get_scrapers()
    
    # Scrape raw jobs
    all_raw_jobs = execute_scraping(scraper_classes, args)
    print(f"\nTotal raw jobs scraped: {len(all_raw_jobs)}")
    
    # Process, verify and save to DB
    verified_count, new_inserted, updated_count, saved_jobs = process_and_save_jobs(
        db, verifier, all_raw_jobs, args
    )
    
    # Print execution summary
    print_summary(len(all_raw_jobs), verified_count, new_inserted, updated_count)
    
    # Export to output JSON file
    export_to_json(saved_jobs, args.output)
    
    # Close database connection
    db.close()

    # Match CV if not skipped
    if not args.skip_matching:
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
                
            except Exception as e:
                print(f"[Error] CV matching failed: {e}")
        else:
            print(f"\n[CV Matcher Info] CV file '{args.cv}' not found. Skipping CV matching.")
            print("To run CV matching, please place your CV PDF file in the root folder (default name: cv.pdf) or specify the path via --cv.")

if __name__ == "__main__":
    main()
