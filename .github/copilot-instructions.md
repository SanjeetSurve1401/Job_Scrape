# Job Scraper AI Skill

This skill enables AI agents to scrape, verify, deduplicate, and store job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on user-defined criteria.

## Capabilities

- **Multi-Source Scraping**: Parallel scraping from LinkedIn, Glassdoor, and Indeed using `python-jobspy` (resilient to Cloudflare blocks).
- **Rule-Based Verification**: Precompiled regex-based verification to filter job listings by title/role match, location matching (including remote), and experience level.
- **Smart Deduplication**: Computes a SHA256 dedup key using `title | company | location` to merge duplicate job listings across platforms.
- **Hybrid Storage**: Saves results to MongoDB Atlas (if configured) or falls back to local in-memory deduplication and exports a clean sequential JSON file.

## Execution Guide for Agents

### 1. Requirements Check
Ensure that Python 3.11+ is installed and check if dependencies are available:
```bash
python3.11 -c "import dotenv, pymongo, bs4, requests, curl_cffi, jobspy"
```
If dependencies are missing, install them:
```bash
python3.11 -m pip install -r requirements.txt
```

### 2. Running a Scrape
Use the `run_command` tool to execute `main.py` with the desired arguments:
```bash
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>" --limit <Max per Source> --output "<JSON Path>"
```

#### Command Arguments
- `--role` (default: `"Software QA Engineer"`): Job title keywords (e.g., `"Python Developer"`, `"Data Analyst"`).
- `--location` (default: `"Pune"`): Search location (supports city names or `"Remote"`).
- `--experience` (default: `"1-3 years"`): Expected experience level (e.g., `"fresher"`, `"1-3 years"`, `"senior"`).
- `--limit` (default: `30`): Maximum raw jobs to fetch per platform.
- `--output` (default: `"scraped_jobs.json"`): Destination file path for verified results.

### 3. Reading Results
Once execution is complete, the results are formatted as a JSON array in the output file specified by `--output`. Read and summarize these results for the user.

## Database & Local Execution modes

- **MongoDB Mode**: If a `MONGO_URI` is present in `.env`, the scraper saves/updates postings in MongoDB Atlas using high-performance find-and-update.
- **Local Fallback Mode**: If `MONGO_URI` is missing, empty, or fails to connect, the scraper automatically falls back to in-memory deduplication. The results are fully processed and saved to the output JSON file. **No database or external server deployment is required for local execution.**