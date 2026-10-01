# Job Scraper Engine — CLI

An advanced, enterprise-grade job scraping and AI matching engine built with a **LangGraph Parallel Pipeline**, **Playwright Session Preservation**, and the **Claude API**.

This engine scrapes job postings from **LinkedIn** and **Glassdoor** concurrently in parallel, filters and verifies them using regex constraints, merges duplicates, scores matching inline against a candidate's CV using Claude, and persists high-quality matches (Score > 6) directly to MongoDB Atlas or a local SQLite database fallback and JSON outputs.

[![Database](https://img.shields.io/badge/Database-MongoDB%20%2F%20Local-orange?style=for-the-badge)](#storage--filter-logic-dip)

---

## Key Features & Capabilities

- **LangGraph Parallel Scraper Pipeline**: Coordinates concurrent scraping, deduplication, inline verification, match scoring, and database operations using an orchestrated StateGraph.
- **Parallel Scraping Concurrency**: Launches LinkedIn and Glassdoor scrapers concurrently in parallel threads (using `ThreadPoolExecutor` within LangGraph nodes) to optimize search wait times.
- **Selective Sources Flag**: Run only specific platforms (e.g., `--sources linkedin` or `--sources glassdoor`) on demand.
- **Playwright Auto-Login & Base64 Cookie Preservation**:
  - Automatically prompts user for login in real browser instances if credentials are missing or expired.
  - Extracts full browser context storage states and saves them as base64-encoded strings inside `.env` to prevent quote truncation errors.
  - Automatically loads and decodes base64 storage states in headless modes for seamless authenticated runs.
- **Automated CV Path Resolution via `.env`**:
  - Configure `CV_PATH` once in `.env` to automatically evaluate jobs without having to type long file paths in terminal commands.
- **Strict Quality Gatekeeper (Score > 6)**:
  - Only jobs matching above 6/10 against the CV are stored in MongoDB, SQLite, and `scraped_jobs.json`.
  - Irrelevant or low-match job listings are automatically dropped from the final output.
- **Clean Single-Table Terminal Output**:
  - Displays a clean, concise summary table of recommended jobs (Score > 6) directly in the console.

---

## LangGraph Workflow Methodology

The system is designed around a modular, event-driven orchestration pipeline managed by **LangGraph** (StateGraph), ensuring robust execution, parallelism, and clean state separation:

### LangGraph Pipeline Nodes:
1. **scrape_* Nodes (Parallel execution)**: Scrapers launch concurrently. They load cookies/storage states directly from `.env` (decoding base64), bypass bot protections using authenticated sessions, and extract raw job detail objects.
2. **verify_jobs Node**: Consolidates all scraped results. Performs SHA-256 deduplication and filters jobs against user-defined criteria (role, location, experience range).
3. **score_jobs Node**: Computes CV match scores (0-10) inline using Claude. Queries cached scores to optimize API usage.
4. **save_jobs Node**: Handles DIP database calls. Saves score-qualified postings (Score > 6) into MongoDB or fallbacks to SQLite and writes to `scraped_jobs.json`.

---

## Mode Comparison

| Mode | Database Connection | Hosting / Deployment | Output Format | Best For |
|---|---|---|---|---|
| **MongoDB Mode** | MongoDB Atlas (via `.env`) | Cloud Database (only saves jobs with Score > 6) | `scraped_jobs.json` + Cloud Database | Long-term tracking, web portals, storing only top matches |
| **Local Fallback Mode** | SQLite Database (.db File) | **No deployment required** (saves jobs with Score > 6) | SQLite `.db` file and `scraped_jobs.json` in outputs folder | Quick local queries, offline audits, persistent local database |

---

## Getting Started & Installation

### 1. Requirements & Setup
Ensure you have **Python 3.10+**. Activate your virtual environment and install dependencies:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Create or edit your `.env` file in the root directory. Below is the reference configuration:

| Variable Name | Required | Purpose / Description | How to Obtain / Configure |
| :--- | :--- | :--- | :--- |
| `CV_PATH` | Recommended | Path to your CV / Resume PDF. Eliminates needing `--cv` in CLI commands. | Set to `resume.pdf` or full absolute path to your resume file. |
| `CLAUDE_API` | Yes (for matching) | Developer key for Anthropic Claude API (also checks `CLAUDE_API_KEY`). | Sign up at [Anthropic Console](https://console.anthropic.com) and create an API key. |
| `MONGO_URI` | No (Falls back to local) | Connection URI for the MongoDB Atlas database. | Connection string from MongoDB Atlas cluster. |
| `DB_NAME` | No | Target MongoDB database name. | e.g., `JobScrapperDB`. |
| `COLLECTION_NAME` | No | Collection name inside your MongoDB database. | e.g., `jobs`. |
| `LINKEDIN_STORAGE_STATE` | Yes | Base64-encoded Playwright session cookies for LinkedIn. | Generated automatically by running `python linkedin_login.py`. |
| `GLASSDOOR_STORAGE_STATE`| Yes | Base64-encoded Playwright session cookies for Glassdoor. | Generated automatically by running `python glassdoor_login.py`. |

> [!NOTE]
> If `MONGO_URI` is omitted, empty, or fails to connect, the engine automatically degrades to **Local Fallback Mode** (writing to `scraped_jobs.json` and local SQLite `outputs/jobs.db`).

---

## CLI Parameter Specifications

| Parameter Name | Argument Flag | Data Type | Default Value | Description / Validation Rules | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Job Role** | `--role` | `String` | `"Software QA Engineer"` | Target title to scrape and verify. | `"QA Engineer"`, `"Python Developer"` |
| **Location** | `--location` | `String` | `"Pune"` | Target search location. | `"Pune"`, `"Remote"`, `"Bangalore"` |
| **Experience** | `--experience`| `String` | `"1-3 years"` | Required experience level or keywords. | `"1 year"`, `"1-3 years"`, `"Entry Level"` |
| **Job Sources** | `--sources` | `String` | `"linkedin,glassdoor"` | Comma-separated list of job platforms to scrape. | `"linkedin"`, `"glassdoor"`, `"linkedin,glassdoor"` |
| **CV Path** | `--cv` | `String` | `None` (reads from `.env`) | Path to your CV PDF file. Defaults to `CV_PATH` from `.env`. | `"resume.pdf"`, `"/path/to/resume.pdf"` |
| **Scrape Limit** | `--limit` | `Integer`| `15` | Total maximum number of raw/verified jobs to fetch. Capped at **25**. | `10`, `20` |
| **Output File** | `--output` | `String` | `"outputs/scraped_jobs.json"` | JSON file path where verified jobs (Score > 6) are exported. | `"outputs/scraped_jobs.json"` |
| **Claude Model** | `--claude-model` | `String` | `"claude haiku 4.5"` | Claude model used for CV matching. | `"claude haiku 4.5"` |

---

### Example CLI Commands

#### 1. Scrape LinkedIn Only (Using CV from `.env`):
```bash
python3 main.py --role "QA Engineer" --location "Remote" --experience "1 year" --sources linkedin
```

#### 2. Scrape Both LinkedIn & Glassdoor:
```bash
python3 main.py --role "Software Engineer" --location "Pune" --experience "1-3 years" --limit 20
```

#### 3. Specify Custom CV File on the fly:
```bash
python3 main.py --role "QA Engineer" --location "Remote" --experience "1 year" --sources linkedin --cv resume.pdf
```

---

## Storage & Filter Logic (DIP)

The engine leverages **Constructor-based Dependency Injection** to dynamically select the storage layer:
1. **MongoDB Mode**: Connections are managed in `DatabaseHandler`. It utilizes a unique index on `dedup_key` to merge postings, but **only saves jobs with a CV match score > 6** to ensure only qualified matches are saved.
2. **Local Fallback Mode**: If MongoDB is offline or unreachable, `LocalDatabaseHandler` connects to SQLite `.db` inside the outputs directory, merges new postings (Score > 6), and writes them directly to `outputs/scraped_jobs.json`. **No server setup or database installation is required.**
