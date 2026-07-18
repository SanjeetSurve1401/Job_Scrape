# Job Scraper Engine — CLI

An advanced, enterprise-grade job scraping and document tailoring engine built with a **LangGraph Parallel Pipeline**, **Playwright Session Preservation**, and the **Claude API**. 

This engine scrapes job postings from **LinkedIn**, **Glassdoor**, and **Indeed** concurrently in parallel, filters/verifies them using regex constraints, merges duplicates, scores matching inline against a CV using Claude Haiku 4.5, tracks token costs dynamically, and persists matches directly to MongoDB Atlas or a local SQLite database fallback.

[![Database](https://img.shields.io/badge/Database-MongoDB%20%2F%20Local-orange?style=for-the-badge)](#database--local-fallback-modes)

---

## Key Features & Capabilities

- **LangGraph Parallel Scraper Pipeline**: Coordinates concurrent scraping, deduplication, inline verification, match scoring, and database operations using an orchestrated StateGraph.
- **Parallel Scraping Concurrency**: Launches LinkedIn, Glassdoor, and Indeed scrapers concurrently in parallel threads (using `ThreadPoolExecutor` within LangGraph nodes) to optimize search wait times from ~45 seconds down to **~15 seconds**.
- **Playwright Auto-Login & Base64 Cookie Preservation**:
  - Automatically prompts user for login in real browser instances if credentials are missing or expired.
  - Extracts full browser context storage states and saves them as base64-encoded strings inside `.env` to prevent quote truncation errors.
  - Automatically loads and decodes base64 storage states in headless modes for seamless authenticated runs.
- **Resume & Cover Letter Document Tailoring**:
  - Automatically customizes CVs and generates professional cover letters tailored to target job descriptions.
  - Outputs documents in both polished **PDF** and **DOCX** formats in the output folders.

- **MongoDB Score Threshold Filtering**: Stored in cloud database **only if** match score is greater than 6.
- **Persistent Local Fallback Database**: SQLite database fallback (`outputs/jobs.db`) loaded automatically on start, merges new listings, and exports results to JSON at the end of the run.

---

## LangGraph Workflow Methodology

The system is designed around a modular, event-driven orchestration pipeline managed by **LangGraph** (StateGraph), ensuring robust execution, parallelism, and clean state separation:

### LangGraph Pipeline Nodes:
1. **scrape_* Nodes (Parallel execution)**: Scrapers launch concurrently. They load cookies/storage states directly from `.env` (decoding base64), bypass bot protections using authenticated sessions, and extract raw job detail objects.
2. **verify_jobs Node**: Consolidates all scraped results. Performs SHA-256 deduplication and filters jobs against user-defined criteria (role, location, experience range).
3. **score_jobs Node**: Computes CV match scores (0-10) inline using Claude Haiku 4.5. Queries the database beforehand to retrieve cached scores to save API costs.
4. **save_jobs Node**: Handles DIP database calls. Saves score-qualified postings (Score > 6) into MongoDB or fallbacks to SQLite and writes to `scraped_jobs.json`.

---

## Mode Comparison

| Mode | Database Connection | Hosting / Deployment | Output Format | Best For |
|---|---|---|---|---|
| **MongoDB Mode** | MongoDB Atlas (via `.env`) | Cloud Database (only saves jobs with Score > 6) | JSON file in current directory | Long-term tracking, web portals, storing only top matches |
| **Local Fallback Mode** | SQLite Database (.db File) | **No deployment required** (saves all jobs) | SQLite .db file and JSON in outputs folder | Quick local queries, offline audits, persistent local database |

---


## Getting Started & Installation

### 1. Requirements & Setup
Ensure you have **Python 3.10+** (Python 3.11 recommended). Install dependencies:
```bash
python3.11 -m pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Create a `.env` file in the root directory. Below is the reference configuration:

| Variable Name | Required | Purpose / Description | How to Obtain / Configure |
| :--- | :--- | :--- | :--- |
| `MONGO_URI` | No (Falls back to local) | Connection URI for the MongoDB Atlas database. | 1. Log in to your [MongoDB Atlas](https://cloud.mongodb.com) account.<br>2. Go to **Database** under Deployment.<br>3. Click **Connect** on your Cluster.<br>4. Select **Drivers** (connection string).<br>5. Copy the connection string and replace `<username>` and `<password>` with database user credentials. |
| `DB_NAME` | No | The target MongoDB database name. | Specify any database name of your choice (e.g., `JobScrapperDB`). If it doesn't exist, MongoDB will create it automatically. |
| `COLLECTION_NAME` | No | The collection name inside your MongoDB database. | Specify the name of the collection where job documents should be stored (e.g., `jobs`). |
| `CLAUDE_API` | Yes (for matching) | Developer key for Anthropic Claude API (also checks `CLAUDE_API_KEY`). | Sign up at [Anthropic Console](https://console.anthropic.com) and create an API key. |
| `MAX_BUDGET_USD` | No | Session limit in USD before halting requests to control costs. | Set a decimal value (e.g., `2.00`). Defaults to `2.0` if not set. |
| `LINKEDIN_STORAGE_STATE` | Yes | Base64-encoded Playwright session cookies for LinkedIn. | Generated automatically by running `python linkedin_login.py`. |
| `GLASSDOOR_STORAGE_STATE`| Yes | Base64-encoded Playwright session cookies for Glassdoor. | Generated automatically by running `python glassdoor_login.py`. |
| `INDEED_STORAGE_STATE`   | Yes | Base64-encoded Playwright session cookies for Indeed. | Generated automatically by running `python indeed_login.py`. |

> [!NOTE]
> If `MONGO_URI` is omitted, empty, or fails to connect, the engine automatically degrades to **Local Fallback Mode** (reading/writing to `scraped_jobs.json` and local SQLite `outputs/jobs.db`).

### 3. Execution (CLI & Manual)
Run the script using:
```bash
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>" [options]
```

---

## CLI Parameter Specifications

| Parameter Name | Argument Flag | Data Type | Default Value | Description / Validation Rules | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Job Role** | `--role` | `String` | `"Software QA Engineer"` | Key title terms to scrape and verify. Precompiled regex filters out non-matching postings. | `"Python Developer"`, `"React Architect"` |
| **Location** | `--location` | `String` | `"Pune"` | Location to search. Supports city names, countries, or `"Remote"`. | `"Pune"`, `"Remote"`, `"Bangalore"` |
| **Experience** | `--experience`| `String` | `"1-3 years"` | Acceptable experience keywords or ranges. Non-matching listings are automatically filtered out. | `"fresher"`, `"1-3 years"`, `"senior"` |
| **Scrape Limit** | `--limit` | `Integer`| `15` | Total maximum number of raw/verified jobs to fetch. Capped at a maximum limit of **25**. | `10`, `25` |
| **Output File** | `--output` | `String` | `"scraped_jobs.json"` | Target JSON file path where verified, deduplicated jobs are exported. | `"results.json"`, `"dev_jobs.json"` |
| **Claude Model** | `--claude-model` | `String` | `"claude haiku 4.5"` | Claude model used for CV matching and document tailoring. Maps to `claude-haiku-4-5-20251001`. | `"claude haiku 4.5"` |


### Example CLI Command:
```bash
python3.11 main.py --role "Software Engineer" --location "Pune" --experience "1-3 years" --limit 20 --output "qa_pune_jobs.json"
```

---

## Storage & Filter Logic (DIP)

The engine leverages **Constructor-based Dependency Injection** to dynamically select the storage layer:
1. **MongoDB Mode**: Connections are managed in `DatabaseHandler`. It utilizes a unique index on `dedup_key` to merge postings, but **only saves jobs with a CV match score > 6** to ensure the cloud database only stores relevant matches.
2. **Local Fallback Mode**: If MongoDB is offline or unreachable, `LocalDatabaseHandler` connects to a SQLite database file `.db` inside the outputs directory, merges/deduplicates new postings, and writes them directly, then exports them back to the output JSON file at the end of the run. **No server setup or database installation is required.**
