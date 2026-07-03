# Job Scraper Engine

A modular, highly resilient, and extensible Job Scraper built in Python. The application scrapes job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on specified criteria (Role, Location, and Experience), verifies them, merges duplicates across multiple platforms, stores them in MongoDB, and outputs a clean JSON file of verified distinct listings.

---

## File Structure

```text
Job_Scrape/
├── .env                        # MongoDB URI and database configurations
├── .gitignore                  # Git exclusions for secrets and credentials
├── requirements.txt            # Python dependencies (pymongo, bs4, requests, lxml)
├── main.py                     # Main CLI Orchestrator and entrypoint
├── job_scraper.mongodb.js      # VS Code MongoDB Playground and analytics queries
├── glassdoor_search.html       # Glassdoor offline search page (fallback source)
├── glassdoor_session.json      # Glassdoor cookies and User-Agent headers
├── linkedin_cookies.json       # (Optional) Logged-in LinkedIn session cookies
├── local_jobs.db               # (Fallback) Local SQLite database
└── src/
    ├── __init__.py
    ├── config.py               # Config loader from .env
    ├── database.py             # Database handler (MongoDB & SQLite fallback)
    ├── models.py               # Job data model
    ├── verifier.py             # Job role, location, and experience verifier
    └── scrapers/
        ├── __init__.py
        ├── base.py             # Abstract base scraper interface
        ├── glassdoor.py        # Glassdoor search and live detail scraper
        ├── linkedin.py         # Cookie-based authenticated LinkedIn scraper
        └── indeed.py           # Public search Indeed scraper
```

---

## Database Features & Site Merging
- **MongoDB Support**: Saves verified distinct jobs to the configured database and collection.
- **Resilient SQLite Fallback**: If MongoDB is not running locally, the program automatically switches to a local SQLite database (`local_jobs.db`).
- **Deduplication**: Job listings are matched case-insensitively on `title`, `company`, and `location`.
- **Site Merging**: If a duplicate listing is found on multiple sites, the database update merges the sources into a comma-separated string (e.g., `"Glassdoor, LinkedIn"`).

---

## Getting Started

### 1. Installation
Install the required packages using pip:
```bash
python3 -m pip install -r requirements.txt
```

### 2. Execution
Run the scraper using the CLI entrypoint:
```bash
python3 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>"
```

#### Options:
- `--role`: The job role to search for (default: `"Software QA Engineer"`).
- `--location`: The location to search for (default: `"Pune"`).
- `--experience`: Required experience range, e.g., `"1-3 years"`, `"Entry Level"`, `"Mid-Senior"` (default: `"1-3 years"`).
- `--limit`: Maximum number of jobs to fetch per source platform (default: `30`).
- `--output`: File path to save the JSON output (default: `"scraped_jobs.json"`).

#### Example:
```bash
python3 main.py --role "Software QA Engineer" --location "India" --experience "1-3 years" --limit 10
```

---

## VS Code MongoDB Playground
The project includes a MongoDB playground script: [job_scraper.mongodb.js](job_scraper.mongodb.js).
1. Connect to your MongoDB server in VS Code using the MongoDB extension.
2. Open `job_scraper.mongodb.js` and click **Run** to:
   - Seed sample data to visualize the merged duplicate schema.
   - Run analytics aggregating total jobs per source site.
   - Aggregate listings by company name.
   - Retrieve all cross-posted listings.