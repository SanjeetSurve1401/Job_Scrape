# Job Scraper Engine — Multi-Tool AI Skill & CLI

**A modular, highly resilient, and extensible Job Scraper packaged as an AI Skill compatible with Cursor, Claude Code, Aider, Windsurf, Copilot, Antigravity, Mistral Vibe, and Hermes Agent.**

This engine scrapes job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on specified criteria (Role, Location, and Experience), verifies them using regex filters, merges duplicates across platforms, and stores them in MongoDB Atlas or falls back to local JSON storage.


[![AI Skill](https://img.shields.io/badge/AI%20Skill-job--scraper-brightgreen?style=for-the-badge)](#ai-skill-integration)
[![Compatibility](https://img.shields.io/badge/AIs-8%20Tools-blue?style=for-the-badge)](#multi-tool-compatibility)
[![Database](https://img.shields.io/badge/Database-MongoDB%20%2F%20Local-orange?style=for-the-badge)](#database--local-fallback-modes)

---

## What is the Job Scraper AI Skill?

The **Job Scraper AI Skill** is a packaged bundle of instructions, schemas, and automation scripts. It gives AI coding assistants native domain expertise to run job scraping operations, parse parameters, and query or format listings directly inside their workflows.

### Mode Comparison

| Mode | Database Connection | Hosting / Deployment | AI Output Format | Best For |
|---|---|---|---|---|
| **MongoDB Mode** | MongoDB Atlas (via `.env`) | Cloud Cluster | JSON file in current directory | Long-term tracking, web portals, multi-run aggregation |
| **Local Fallback Mode** | None (In-Memory Dedup) | **No deployment required** | JSON file in current directory | Quick local queries, offline audits, developer CLI runs |

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
├── main.py                     # Main CLI Orchestrator and entrypoint
├── SKILL.md                    # Core AI Skill Manifest
├── .cursorrules                # Cursor System Rules
├── CONVENTIONS.md              # Aider System Rules
├── glassdoor_search.html       # Local offline Glassdoor cache
├── scripts/
│   └── export_rules.py         # Automates exporting skill specs to 8 AI platforms
└── src/
    ├── __init__.py
    ├── config.py               # Config loader from .env
    ├── database.py             # MongoDB Handler + LocalDatabaseHandler fallback
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


#### Environment Variables Specification:

| Variable Name | Required | Purpose / Description | How to Obtain / Configure |
| :--- | :--- | :--- | :--- |
| `MONGO_URI` | No (Falls back to local) | Connection URI for the MongoDB Atlas database. | 1. Log in to your [MongoDB Atlas](https://cloud.mongodb.com) account.<br>2. Go to **Database** under Deployment.<br>3. Click **Connect** on your Cluster.<br>4. Select **Drivers** (connection string).<br>5. Copy the connection string and replace `<username>` and `<password>` with your database user credentials. |
| `DB_NAME` | No | The target MongoDB database name. | Specify any database name of your choice (e.g., `JobScrapperDB`). If it doesn't exist, MongoDB will create it automatically. |
| `COLLECTION_NAME` | No | The collection name inside your MongoDB database. | Specify the name of the collection where job documents should be stored (e.g., `jobs`). |
| `GLASSDOOR_USER_AGENT`| Yes (for Glassdoor) | User-Agent header value to bypass Glassdoor security blocks. | 1. Open [Glassdoor](https://www.glassdoor.com) in your browser and log in.<br>2. Open Developer Tools (`F12` or Right-click -> **Inspect**).<br>3. Go to the **Network** tab and refresh the page.<br>4. Click on any document/request to `glassdoor.com`.<br>5. Scroll down to **Request Headers** and copy the full value of the `User-Agent` key. |
| `GLASSDOOR_COOKIE` | Yes (for Glassdoor) | Authenticated cookie header string for session bypass. | 1. Follow the same browser Network inspection steps as above.<br>2. Under the **Request Headers** section, find the `Cookie` header.<br>3. Copy the entire cookie string value and paste it here. |


> [!NOTE]
> If `MONGO_URI` is omitted, empty, or fails to connect, the engine automatically degrades to **Local Fallback Mode** (saving directly to JSON).


### 3. Execution (CLI & Manual)
Run the script using:
```bash
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>" [options]
```

---

## AI Skill Parameter Specifications

When prompting or calling the tool, use the following parameter specifications:

| Parameter Name | Argument Flag | Data Type | Default Value | Description / Validation Rules | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Job Role** | `--role` | `String` | `"Software QA Engineer"` | Key title terms to scrape and verify. Precompiled regex filters out non-matching postings. | `"Python Developer"`, `"React Architect"` |
| **Location** | `--location` | `String` | `"Pune"` | Location to search. Supports city names, countries, or `"Remote"` for remote-only positions. | `"Pune"`, `"Remote"`, `"Bangalore"` |
| **Experience** | `--experience`| `String` | `"1-3 years"` | Acceptable experience keywords or ranges. Non-matching listings are automatically filtered out. | `"fresher"`, `"1-3 years"`, `"senior"` |
| **Scrape Limit** | `--limit` | `Integer`| `30` | Total maximum number of raw job postings to fetch across all platforms. | `15`, `50` |
| **Output File** | `--output` | `String` | `"scraped_jobs.json"` | Target JSON file path where verified, deduplicated jobs are exported (created at the same location where the AI is running). | `"results.json"`, `"dev_jobs.json"` |

### Example CLI Command:
```bash
python3.11 main.py --role "Software Engineer" --location "Pune" --experience "1-3 years" --limit 20 --output "qa_pune_jobs.json"
```

---

## Database & Local Fallback Modes

The engine leverages **Constructor-based Dependency Injection** to dynamically select the storage layer:
1. **With Database Access**: If `MONGO_URI` is provided, the scraper connects to MongoDB Atlas, utilizes a unique index on `dedup_key` to merge multi-source postings, updates existing documents, and appends new ones.
2. **Without Deployment/Database**: If MongoDB is offline, unconfigured, or unreachable, the orchestrator triggers `LocalDatabaseHandler` which executes in-memory deduplication. Verified listings are written to the JSON file with consecutive serial numbers. **No server setup or database installation is required.**

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
