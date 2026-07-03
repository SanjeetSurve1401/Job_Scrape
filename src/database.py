import re
import sqlite3
from typing import Optional, Tuple
from datetime import datetime
from pymongo import MongoClient
from src.config import Config
from src.models import Job

class DatabaseHandler:
    def __init__(self):
        self.use_fallback = False
        try:
            self.client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=1500)
            # Trigger a ping to force connection check
            self.client.admin.command('ping')
            self.db = self.client[Config.DB_NAME]
            self.collection = self.db[Config.COLLECTION_NAME]
            print("Connected to MongoDB successfully.")
        except Exception as e:
            print(f"Warning: MongoDB connection failed ({e}). Falling back to SQLite local database.")
            self.use_fallback = True
            self._setup_sqlite()

    def _setup_sqlite(self):
        """Initializes a local SQLite database for fallback storage."""
        self.conn = sqlite3.connect("local_jobs.db")
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                company TEXT,
                location TEXT,
                about_job TEXT,
                site TEXT,
                url TEXT,
                salary TEXT,
                experience_required TEXT,
                scraped_at TEXT,
                job_id TEXT
            )
        """)
        self.conn.commit()

    def _save_mongodb(self, job: Job) -> Tuple[bool, dict]:
        """Saves or updates job in MongoDB."""
        query = {
            "title": {"$regex": f"^{re.escape(job.title.strip())}$", "$options": "i"},
            "company": {"$regex": f"^{re.escape(job.company.strip())}$", "$options": "i"},
            "location": {"$regex": f"^{re.escape(job.location.strip())}$", "$options": "i"}
        }

        existing_job = self.collection.find_one(query)

        if existing_job:
            existing_sites = [s.strip() for s in existing_job.get("site", "").split(",") if s.strip()]
            new_sites = job.site if isinstance(job.site, list) else [job.site]
            
            combined_sites = list(existing_sites)
            for site in new_sites:
                cleaned_site = site.strip()
                if cleaned_site and cleaned_site not in combined_sites:
                    combined_sites.append(cleaned_site)
            
            merged_sites_str = ", ".join(combined_sites)
            
            update_fields = {
                "site": merged_sites_str
            }
            
            if not existing_job.get("about_job") and job.about_job:
                update_fields["about_job"] = job.about_job
            if not existing_job.get("salary") and job.salary:
                update_fields["salary"] = job.salary
            if not existing_job.get("url") and job.url:
                update_fields["url"] = job.url

            self.collection.update_one({"_id": existing_job["_id"]}, {"$set": update_fields})
            updated_doc = self.collection.find_one({"_id": existing_job["_id"]})
            updated_doc["_id"] = str(updated_doc["_id"])
            return False, updated_doc
        else:
            job_dict = job.to_dict()
            result = self.collection.insert_one(job_dict)
            job_dict["_id"] = str(result.inserted_id)
            return True, job_dict

    def _save_sqlite(self, job: Job) -> Tuple[bool, dict]:
        """Saves or updates job in SQLite fallback."""
        # Find exact case-insensitive match
        self.cursor.execute(
            "SELECT id, site, about_job, salary, url FROM jobs WHERE LOWER(TRIM(title)) = ? AND LOWER(TRIM(company)) = ? AND LOWER(TRIM(location)) = ?",
            (job.title.strip().lower(), job.company.strip().lower(), job.location.strip().lower())
        )
        existing_job = self.cursor.fetchone()

        if existing_job:
            row_id, existing_sites_str, db_about, db_salary, db_url = existing_job
            
            existing_sites = [s.strip() for s in existing_sites_str.split(",") if s.strip()]
            new_sites = job.site if isinstance(job.site, list) else [job.site]
            
            combined_sites = list(existing_sites)
            for site in new_sites:
                cleaned_site = site.strip()
                if cleaned_site and cleaned_site not in combined_sites:
                    combined_sites.append(cleaned_site)
            
            merged_sites_str = ", ".join(combined_sites)
            
            # Merge updates
            about_val = db_about if db_about else job.about_job
            salary_val = db_salary if db_salary else job.salary
            url_val = db_url if db_url else job.url
            
            self.cursor.execute(
                "UPDATE jobs SET site = ?, about_job = ?, salary = ?, url = ? WHERE id = ?",
                (merged_sites_str, about_val, salary_val, url_val, row_id)
            )
            self.conn.commit()
            
            return False, {
                "id": row_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "about_job": about_val,
                "site": merged_sites_str,
                "url": url_val,
                "salary": salary_val,
                "experience_required": job.experience_required,
                "scraped_at": datetime.utcnow().isoformat(),
                "job_id": job.job_id
            }
        else:
            # Insert new job
            site_str = ", ".join(job.site) if isinstance(job.site, list) else job.site
            self.cursor.execute(
                """INSERT INTO jobs (title, company, location, about_job, site, url, salary, experience_required, scraped_at, job_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.title,
                    job.company,
                    job.location,
                    job.about_job,
                    site_str,
                    job.url,
                    job.salary,
                    job.experience_required,
                    job.scraped_at.isoformat() if isinstance(job.scraped_at, datetime) else job.scraped_at,
                    job.job_id
                )
            )
            self.conn.commit()
            row_id = self.cursor.lastrowid
            
            return True, {
                "id": row_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "about_job": job.about_job,
                "site": site_str,
                "url": job.url,
                "salary": job.salary,
                "experience_required": job.experience_required,
                "scraped_at": job.scraped_at.isoformat() if isinstance(job.scraped_at, datetime) else job.scraped_at,
                "job_id": job.job_id
            }

    def save_job(self, job: Job) -> Tuple[bool, dict]:
        """Saves a job to the configured database (MongoDB or SQLite fallback)."""
        # Sanitize text fields to prevent NoneType errors when calling string operations
        job.title = (job.title or "").strip()
        job.company = (job.company or "").strip()
        job.location = (job.location or "").strip()
        job.about_job = (job.about_job or "").strip()

        if not self.use_fallback:
            try:
                return self._save_mongodb(job)
            except Exception as e:
                print(f"MongoDB operation failed ({e}). Switching to SQLite fallback database.")
                self.use_fallback = True
                self._setup_sqlite()
                return self._save_sqlite(job)
        else:
            return self._save_sqlite(job)

    def close(self):
        """Closes connection to the database."""
        if not self.use_fallback:
            try:
                self.client.close()
            except:
                pass
        else:
            try:
                self.conn.close()
            except:
                pass
