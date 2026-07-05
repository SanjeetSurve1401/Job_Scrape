# Job Scraper AI Skill

This skill enables AI agents to scrape, verify, deduplicate, score, and store job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on user-defined criteria.

## Capabilities

- **Multi-Source Scraping & Balanced Distribution**: Scrapes jobs from LinkedIn, Glassdoor, and Indeed in parallel (using a ThreadPoolExecutor) by dynamically dividing the target limit across active platforms to ensure fast and balanced results.
- **Dynamic Retry Scraping Loop**: If the number of verified jobs is less than the target limit (due to verification filtering), the scraper automatically runs up to 5 attempts with increased scraping depths to reach the target limit.
- **Rule-Based Verification**: Filters job listings by title/role match, location matching (including remote), and experience level.
- **Inline CV Matching**: Evaluates jobs against the candidate's CV using Groq (LLM) inline during the verification loop (instead of at the end) with built-in caching (to skip already scored jobs) and a rate-limiting delay of 2.0 seconds.
- **Smart Deduplication**: Computes a SHA256 dedup key using `title | company | location` to merge duplicate job listings across platforms.
- **Hybrid & Scored Storage Filtering**:
  - **MongoDB Mode**: If a `MONGO_URI` is present in `.env`, the scraped jobs are saved/updated to MongoDB Atlas *only if* their CV match score is greater than 6.
  - **Local Fallback Mode**: If MongoDB is not connected, it falls back to a persistent local JSON database file (specified by `--output`) which loads existing jobs at startup and merges new ones.

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
- `--limit` (default: `15`): Total maximum raw/verified jobs to fetch (maximum limit allowed is 25).
- `--output` (default: `"scraped_jobs.json"`): Destination JSON file path for verified results (created at the same location where the AI is running).
- `--groq-model` (default: `"llama-3.1-8b-instant"`): Groq model to use for CV matching.

### 3. Output Generation & Results
Once execution is complete, the AI must create a JSON output file containing the verified results at the same location where the AI is running (the current working directory). The output format must be JSON.