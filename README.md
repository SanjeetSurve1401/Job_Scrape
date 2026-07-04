# Job Scraper Engine

A modular, highly resilient, and extensible Job Scraper built in Python following  optimized for performance with parallel processing.

The application scrapes job postings from **LinkedIn**, **Glassdoor**, and **Indeed** based on specified criteria (Role, Location, and Experience), verifies them, merges duplicates across multiple platforms, stores them in MongoDB Atlas, and outputs a clean JSON file of verified distinct listings.

---

## File Structure

```text
Job_Scrape/
├── .env                        # MongoDB URI, Glassdoor credentials, and database config
├── .gitignore                  
├── requirements.txt            
├── main.py                     # Main CLI Orchestrator and entrypoint
├── glassdoor_search.html       
└── src/
    ├── __init__.py
    ├── config.py               # Config loader from .env
    ├── database.py             # Database handler (MongoDB Atlas integration)
    ├── interfaces.py           
    ├── models.py               # Job data model & SHA256 dedup hashing
    ├── verifier.py             # Job role, location, and experience verifier (Precompiled regex)
    └── scrapers/
        ├── __init__.py         # Dynamic Scraper Auto-Discovery
        ├── base.py             
        ├── glassdoor.py        # Glassdoor search and offline parsing (RSC support)
        ├── linkedin.py         
        └── indeed.py           
```

---

## Getting Started

### 1. Requirements & Installation
The scraper runs optimally on **Python 3.10+** (using the `python-jobspy` scraping engine to bypass Cloudflare). It will gracefully fall back to custom `curl_cffi` / guest scrapers on older Python versions.

Install the required packages:
```bash
python3.11 -m pip install -r requirements.txt
```

### 2. Environment Configuration (`.env`)
Create a `.env` file in the root of the repository and configure the following variables:

| Variable Name | Purpose / Description | How to Obtain / Process |
| :--- | :--- | :--- |
| `MONGO_URI` | Connection URI for the MongoDB database. | 1. Log in to [MongoDB Atlas](https://cloud.mongodb.com).<br>2. Click **Connect** on your Database Cluster.<br>3. Select **Connect your application** (driver connection).<br>4. Copy the connection string and replace `<username>` and `<password>` with your database user credentials. |
| `DB_NAME` | The MongoDB database name. | Specify any name for your database (e.g., `Job12345`). |
| `COLLECTION_NAME` | The collection name inside MongoDB. | Specify the collection where jobs should be saved (e.g., `jobs1234`). |
| `GLASSDOOR_USER_AGENT` | User-Agent header value to bypass Glassdoor blocks. | 1. Navigate to [Glassdoor](https://www.glassdoor.com) in your browser.<br>2. Login to your account.<br>3. Open Developer Tools (`F12` or right-click -> **Inspect**).<br>3. Go to the **Network** tab and refresh.<br>4. Click on any document/request to `glassdoor.com`.<br>5. Under **Request Headers**, copy the full value of the `User-Agent` key. |
| `GLASSDOOR_COOKIE` | Cookie header value to authenticate Glassdoor requests. | 1. Follow the same browser Network inspection steps as above.<br>2. Scroll down under the **Request Headers** section to find the `Cookie` header.<br>3. Copy the entire cookie string value and paste it. |

### 3. Execution
Run the scraper using Python 3.11:
```bash
python3.11 main.py --role "<Job Role>" --location "<Location>" --experience "<Experience Range>"
```

#### Options:

| Option | Type | Default Value | Description | Examples |
| :--- | :--- | :--- | :--- | :--- |
| `--role` | String | `"Software QA Engineer"` | Job role, title, or keywords to search for. | `"Software QA Engineer"`, `"Python Developer"` |
| `--location` | String | `"Pune"` | The target location for job postings. Remote searches are also supported. | `"Pune"`, `"Remote"`, `"Bangalore"` |
| `--experience` | String | `"1-3 years"` | Required experience criteria. Supports ranges, exact years, and keywords. | `"fresher"`, `"1-3 years"`, `"mid"`, `"senior"` |
| `--limit` | Integer | `30` | Maximum number of job postings to scrape per source platform. | `15`, `50` |
| `--output` | String | `"scraped_jobs.json"` | File path where the clean, verified, deduplicated JSON output is saved. | `"results.json"` |

#### Example:
```bash
python3.11 main.py --role "Software Engineer" --location "Pune" --experience "1-3 years" --limit 30 --output "scraped_jobs.json"
```
---
