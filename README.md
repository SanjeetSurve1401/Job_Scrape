# Job Scraper Engine — Multi-Tool AI Skill & CLI

**A modular, highly resilient, and parallelized Job Scraper packaged as an AI Skill compatible with Cursor, Claude Code, Aider, Windsurf, Copilot, Antigravity, Mistral Vibe, and Hermes Agent.**

This engine scrapes job postings from **LinkedIn**, **Glassdoor**, and **Indeed** concurrently in parallel, verifies them using regex filters, merges duplicates, scores matching inline against a CV using Groq (LLM), and stores matches in MongoDB Atlas or falls back to a persistent local JSON database.

[![AI Skill](https://img.shields.io/badge/AI%20Skill-job--scraper-brightgreen?style=for-the-badge)](#ai-skill-integration)
[![Compatibility](https://img.shields.io/badge/AIs-8%20Tools-blue?style=for-the-badge)](#multi-tool-compatibility)
[![Database](https://img.shields.io/badge/Database-MongoDB%20%2F%20Local-orange?style=for-the-badge)](#database--local-fallback-modes)

---

## Key Features & Capabilities

- **Parallel Scraping Concurrency**: Launches LinkedIn, Glassdoor, and Indeed scrapers concurrently in parallel threads (using `ThreadPoolExecutor`) to optimize wait times from ~45 seconds down to **~15 seconds**.
- **Balanced Limit Distribution**: Dynamically divides the target limit (default: 15, max: 25) evenly across active platforms to retrieve a balanced set of listings instead of fetching from a single source.
- **Dynamic Scraper Retry Loop**: If the number of verified jobs falls short of the target limit (due to verification filtering), the scraper runs up to **5 attempts** with deeper search offsets until the target limit is met.
- **Inline CV Matching & Caching**:
  - Scores verified jobs against a PDF CV using Groq (`llama-3.1-8b-instant`) *inline* during processing.
  - Automatically queries the database using `find_job_by_key` to retrieve cached scores and skip redundant API calls.
  - Implements a rate-limit safe `2.0` seconds delay between Groq calls.
- **MongoDB Score Threshold Filtering**: If MongoDB is connected, jobs are stored in the cloud database **only if** their match score is greater than 6 (score 6+).
- **Persistent Local Fallback Database**: If MongoDB is disconnected, it falls back to a persistent local JSON database (specified by `--output`) which loads existing jobs at startup and merges new listings.

---

## What is the Job Scraper AI Skill?

The **Job Scraper AI Skill** is a packaged bundle of instructions, schemas, and automation scripts. It gives AI coding assistants native domain expertise to run job scraping operations, parse parameters, and query or format listings directly inside their workflows.

### Mode Comparison

| Mode | Database Connection | Hosting / Deployment | AI Output Format | Best For |
|---|---|---|---|---|
| **MongoDB Mode** | MongoDB Atlas (via `.env`) | Cloud Database (only saves jobs with Score > 6) | JSON file in current directory | Long-term tracking, web portals, storing only top matches |
| **Local Fallback Mode** | None (Local JSON File) | **No deployment required** (saves all jobs) | JSON file in current directory | Quick local queries, offline audits, persistent local database |

---

## Multi-Tool Compatibility

This skill is compatible with **8 major AI coding assistants and agents**. You can generate native configurations for all platforms by running the export script:

```bash
python3.11 scripts/export_rules.py
```

This creates the following native files automatically:

| AI Tool / Agent | Target Format | Configuration File Generated |
| :--- | :--- | :--- |
| **Google Antigravity** | `SKILL.md` (Manifest) | [SKILL.md](file:/Jobs_scrapper/Job_Scrape/SKILL.md) (Root) |
| **Cursor** | `.cursorrules` (System Prompt) | `.cursorrules` (Root) |
| **Aider** | `CONVENTIONS.md` (System Rules) | `CONVENTIONS.md` (Root) |
| **Windsurf** | `.windsurf/rules` | `.windsurf/rules/job-scraper.md` |
| **GitHub Copilot** | `.github/copilot-instructions.md` | `.github/copilot-instructions.md` |
| **Mistral Vibe** | `.vibe/skills/` | `.vibe/skills/job-scraper/SKILL.md` |
| **Hermes Agent** | `.hermes/skills/` | `.hermes/skills/job-scraper/SKILL.md` |
| **Claude Code** | Custom Skill folder | Copies of `SKILL.md` inside target agent directories |

---

## File Structure

```text
Job_Scrape/
├── .env                        # MongoDB URI, Glassdoor credentials, and database config
├── .gitignore                  
├── requirements.txt            
├── main.py                     # Main CLI Orchestrator (scrapes, verifies, scores inline, exports)
├── SKILL.md                    # Core AI Skill Manifest
├── .cursorrules                # Cursor System Rules
├── CONVENTIONS.md              # Aider System Rules
├── glassdoor_search.html       # Local offline Glassdoor cache
├── scripts/
│   └── export_rules.py         # Automates exporting skill specs to 8 AI platforms
└── src/
    ├── __init__.py
    ├── config.py               # Config loader from .env
    ├── database.py             # MongoDB Handler + Persistent Local JSON Handler
    ├── interfaces.py           # Database and Verifier interfaces (DIP)
    ├── models.py               # Job data model & SHA256 dedup hashing
    ├── verifier.py             # Regex job role, location, and experience verifier
    └── scrapers/
        ├── __init__.py         # Dynamic Scraper Auto-Discovery
        ├── base.py             
        ├── glassdoor.py        # Glassdoor search and offline parsing
        ├── linkedin.py         # LinkedIn scraper using python-jobspy
        └── indeed.py           # Indeed scraper using python-jobspy
```

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
| `GROQ_API` | Yes (for matching) | Developer key for Groq Cloud API. | Sign up at [Groq Console](https://console.groq.com) and create an API key. |
| `GLASSDOOR_USER_AGENT`| Yes (for Glassdoor) | User-Agent header value to bypass Glassdoor security blocks. | 1. Open [Glassdoor](https://www.glassdoor.com) and log in.<br>2. Open Developer Tools (`F12` -> Network).<br>3. Inspect the headers of any document/request to `glassdoor.com` and copy the `User-Agent` key. |
| `GLASSDOOR_COOKIE` | Yes (for Glassdoor) | Authenticated cookie header string for session bypass. | Copy the full `Cookie` header value from request headers on any Glassdoor page request. |

> [!NOTE]
> If `MONGO_URI` is omitted, empty, or fails to connect, the engine automatically degrades to **Local Fallback Mode** (reading/writing to `scraped_jobs.json`).

### 3. Execution (CLI & Manual)
Run the script using:
```bash
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>" [options]
```

---

## AI Skill Parameter Specifications

| Parameter Name | Argument Flag | Data Type | Default Value | Description / Validation Rules | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Job Role** | `--role` | `String` | `"Software QA Engineer"` | Key title terms to scrape and verify. Precompiled regex filters out non-matching postings. | `"Python Developer"`, `"React Architect"` |
| **Location** | `--location` | `String` | `"Pune"` | Location to search. Supports city names, countries, or `"Remote"`. | `"Pune"`, `"Remote"`, `"Bangalore"` |
| **Experience** | `--experience`| `String` | `"1-3 years"` | Acceptable experience keywords or ranges. Non-matching listings are automatically filtered out. | `"fresher"`, `"1-3 years"`, `"senior"` |
| **Scrape Limit** | `--limit` | `Integer`| `15` | Total maximum number of raw/verified jobs to fetch. Capped at a maximum limit of **25**. | `10`, `25` |
| **Output File** | `--output` | `String` | `"scraped_jobs.json"` | Target JSON file path where verified, deduplicated jobs are exported. | `"results.json"`, `"dev_jobs.json"` |
| **Groq Model** | `--groq-model` | `String` | `"llama-3.1-8b-instant"` | Groq model used for inline match scoring. | `"llama-3.1-8b-instant"`, `"llama-3.3-70b-versatile"` |

### Example CLI Command:
```bash
python3.11 main.py --role "Software Engineer" --location "Pune" --experience "1-3 years" --limit 20 --output "qa_pune_jobs.json"
```

---

## Storage & Filter Logic (DIP)

The engine leverages **Constructor-based Dependency Injection** to dynamically select the storage layer:
1. **MongoDB Mode**: Connections are managed in `DatabaseHandler`. It utilizes a unique index on `dedup_key` to merge postings, but **only saves jobs with a CV match score > 6** to ensure the cloud database only stores relevant matches.
2. **Local Fallback Mode**: If MongoDB is offline or unreachable, `LocalDatabaseHandler` loads existing jobs from the output JSON file at startup, merges/deduplicates new postings, and writes the complete history back to the output JSON file. **No server setup or database installation is required.**

---

## Loading the Skill in AI Agents

### Google Antigravity Configuration
Add the project directory to the `skills_paths` config:
```python
from google.antigravity import Agent, LocalAgentConfig

config = LocalAgentConfig(
    skills_paths=["/Users/pc_name/Documents/Jobs_scrapper/Job_Scrape"]
)

async with Agent(config) as agent:
    response = await agent.chat("Find me software engineer jobs in Remote with 1-3 years experience")
    print(await response.text())
```

### Cursor & Windsurf Instructions
Since `export_rules.py` generates `.cursorrules` and `.windsurf/rules/job-scraper.md`, the AI assistant in Cursor or Windsurf will automatically read the instructions when you open this project workspace. Simply ask:
> *"Run the job scraper for Python Developers in Pune requiring 3-5 years experience with a limit of 10."*
