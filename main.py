import argparse
import json
import os
from datetime import datetime
from src.database import DatabaseHandler
from src.verifier import JobVerifier
from src.scrapers.glassdoor import GlassdoorScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.indeed import IndeedScraper

def main():
    parser = argparse.ArgumentParser(description="SOLID Job Scraper for LinkedIn, Glassdoor, and Indeed")
    parser.add_argument("--role", type=str, default="Software QA Engineer", help="Job role to search for")
    parser.add_argument("--location", type=str, default="Pune", help="Location to search for")
    parser.add_argument("--experience", type=str, default="1-3 years", help="Required experience level (e.g., '1-3 years', 'Entry Level')")
    parser.add_argument("--output", type=str, default="scraped_jobs.json", help="Path to save the JSON output file")
    parser.add_argument("--limit", type=int, default=30, help="Max jobs to scrape per source (default: 30)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"Starting Job Scraper Engine")
    print(f"Role: {args.role}")
    print(f"Location: {args.location}")
    print(f"Experience Criteria: {args.experience}")
    print(f"Limit per source: {args.limit}")
    print("=" * 60)

    # Initialize Database and Verifier
    try:
        db = DatabaseHandler()
        print("Connected to MongoDB successfully.")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        print("Please ensure MongoDB is running and MONGO_URI in .env is correct.")
        return

    verifier = JobVerifier()
    
    # Register all active scrapers conforming to BaseScraper interface (OCP)
    scrapers = [
        GlassdoorScraper(),
        LinkedInScraper(),
        IndeedScraper()
    ]
    
    all_scraped_jobs = []
    
    # Run scrapers
    for scraper in scrapers:
        scraper_name = scraper.__class__.__name__
        try:
            print(f"\n[Scraping] Launching {scraper_name}...")
            jobs = scraper.scrape(args.role, args.location, args.experience, limit=args.limit)
            print(f"[Scraping] {scraper_name} returned {len(jobs)} jobs.")
            all_scraped_jobs.extend(jobs)
        except Exception as e:
            print(f"[Error] Scraper {scraper_name} failed: {e}")
            
    print(f"\nTotal raw jobs scraped: {len(all_scraped_jobs)}")
    
    # Verify and insert distinct jobs
    verified_jobs_count = 0
    new_jobs_inserted = 0
    existing_jobs_updated = 0
    
    # We will accumulate the saved/updated jobs to write to JSON output
    saved_jobs_list = []

    print("\n[Verifying & Saving] Processing jobs...")
    for job in all_scraped_jobs:
        # Verify job matches criteria
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
        else:
            # Job didn't match verification criteria, skipped
            pass

    # Print Summary statistics
    print("\n" + "=" * 60)
    print("Execution Summary:")
    print(f"  - Total scraped: {len(all_scraped_jobs)}")
    print(f"  - Total verified: {verified_jobs_count}")
    print(f"  - Newly inserted in MongoDB: {new_jobs_inserted}")
    print(f"  - Existing jobs updated/merged: {existing_jobs_updated}")
    print("=" * 60)

    # Write output to JSON
    # Remove MongoDB's internal _id if needed, or serialize it. (We already converted it to string in DatabaseHandler.save_job)
    try:
        with open(args.output, 'w', encoding='utf-8') as json_file:
            json.dump(saved_jobs_list, json_file, indent=2, ensure_ascii=False)
        print(f"\nSuccessfully wrote {len(saved_jobs_list)} distinct, verified jobs to '{args.output}'.")
    except Exception as e:
        print(f"Error writing to JSON output file: {e}")

    # Close DB connection
    db.close()

if __name__ == "__main__":
    main()
