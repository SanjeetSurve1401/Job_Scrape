---
name: job-scraper
description: A modular and resilient Job Scraper for LinkedIn, Glassdoor, and Indeed. Automates job scraping, filters by role/location/experience, merges duplicates, and supports MongoDB or local JSON storage.
---

# Job Scraper AI Skill

This skill enables AI agents to scrape, verify, deduplicate, and store job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on user-defined criteria.

## Capabilities

- **Multi-Source Scraping**: Parallel scraping from LinkedIn, Glassdoor, and Indeed using `python-jobspy` (resilient to Cloudflare blocks).
- **Rule-Based Verification**: Precompiled regex-based verification to filter job listings by title/role match, location matching (including remote), and experience level.
- **Smart Deduplication**: Computes a SHA256 dedup key using `title | company | location` to merge duplicate job listings across platforms.
- **Hybrid Storage**: Saves results to MongoDB Atlas (if configured) or falls back to local in-memory deduplication. The AI must create a JSON output file at the same location where the AI is running.

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
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>" --limit <Total Max Jobs> --output "<JSON Path>"
```

#### Command Arguments
- `--role` (default: `"Software QA Engineer"`): Job title keywords (e.g., `"Python Developer"`, `"Data Analyst"`).
- `--location` (default: `"Pune"`): Search location (supports city names or `"Remote"`).
- `--experience` (default: `"1-3 years"`): Expected experience level (e.g., `"fresher"`, `"1-3 years"`, `"senior"`).
- `--limit` (default: `30`): Total maximum raw jobs to fetch across all platforms.
- `--output` (default: `"scraped_jobs.json"`): Destination JSON file path for verified results (created at the same location where the AI is running).

### 3. Output Generation & Results
Once execution is complete, the AI must create a JSON output file containing the verified results at the same location where the AI is running (the current working directory). The output format must be JSON.

## Database & Local Execution modes

- **MongoDB Mode**: If a `MONGO_URI` is present in `.env`, the scraper saves/updates postings in MongoDB Atlas using high-performance find-and-update.
- **Local Fallback Mode**: If `MONGO_URI` is missing, empty, or fails to connect, the scraper automatically falls back to in-memory deduplication. The results are fully processed and saved to the output JSON file. **No database or external server deployment is required for local execution.**
