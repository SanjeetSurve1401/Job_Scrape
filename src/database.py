import os
import json
import sqlite3
from datetime import datetime
from typing import Tuple, List, Dict, Any
from pymongo import MongoClient, ReturnDocument
from src.interfaces import DatabaseInterface
from src.models import Job

class DatabaseHandler(DatabaseInterface):
    def __init__(self, uri: str, db_name: str, collection_name: str):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        # Trigger a ping to force connection check
        self.client.admin.command('ping')
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        
        # Create an index on dedup_key to ensure O(log n) search time
        self.collection.create_index("dedup_key", unique=True, sparse=True)

    def save_job(self, job: Job) -> Tuple[bool, dict]:
        """Saves or updates a job in MongoDB with O(log n) deduplication using dedup_key."""
        # Sanitize local copies of strings instead of mutating the input Job object
        title = (job.title or "").strip()
        company = (job.company or "").strip()
        location = (job.location or "").strip()
        about_job = (job.about_job or "").strip()

        dedup_key = job.dedup_key()

        # Step 1: Find existing job by dedup_key index
        existing_job = self.collection.find_one({"dedup_key": dedup_key})

        if existing_job:
            # Merge site sources using set for O(1) membership operations
            existing_sites = {s.strip() for s in existing_job.get("site", "").split(",") if s.strip()}
            new_sites = job.site if isinstance(job.site, list) else [job.site]
            for s in new_sites:
                cleaned_site = s.strip()
                if cleaned_site:
                    existing_sites.add(cleaned_site)
            
            merged_sites_str = ", ".join(sorted(existing_sites))

            update_fields = {"site": merged_sites_str}

            # Fill in missing fields from the new source
            if not existing_job.get("about_job") and about_job:
                update_fields["about_job"] = about_job
            if not existing_job.get("salary") and job.salary:
                update_fields["salary"] = job.salary
            if not existing_job.get("url") and job.url:
                update_fields["url"] = job.url
            if hasattr(job, "score") and job.score is not None:
                update_fields["score"] = job.score
            if hasattr(job, "explanation") and job.explanation:
                update_fields["explanation"] = job.explanation
            if hasattr(job, "ats_score") and job.ats_score is not None:
                update_fields["ats_score"] = job.ats_score

            # Perform single round-trip update and fetch
            updated_doc = self.collection.find_one_and_update(
                {"dedup_key": dedup_key},
                {"$set": update_fields},
                return_document=ReturnDocument.AFTER
            )
            updated_doc["_id"] = str(updated_doc["_id"])
            return False, updated_doc
        else:
            # Insert new job
            job_dict = job.to_dict()
            # Ensure sanitized values are stored
            job_dict["title"] = title
            job_dict["company"] = company
            job_dict["location"] = location
            job_dict["about_job"] = about_job
            
            result = self.collection.insert_one(job_dict)
            job_dict["_id"] = str(result.inserted_id)
            return True, job_dict

    def find_job_by_key(self, dedup_key: str) -> dict:
        """Finds a job by its deduplication key in MongoDB."""
        doc = self.collection.find_one({"dedup_key": dedup_key})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def get_all_jobs(self) -> list:
        """Returns all jobs stored in the MongoDB collection."""
        jobs = list(self.collection.find({}))
        for job in jobs:
            job["_id"] = str(job["_id"])
        return jobs

    def close(self) -> None:
        """Closes connection to MongoDB."""
        try:
            self.client.close()
        except Exception as e:
            print(f"Warning: error closing MongoDB connection: {e}")


class LocalDatabaseHandler(DatabaseInterface):
    """Local SQLite database fallback when MongoDB is not available."""
    def __init__(self, filename: str = "scraped_jobs.json"):
        # If the filename ends with .json, change it to .db
        if filename.endswith(".json"):
            self.filename = filename.rsplit(".json", 1)[0] + ".db"
        else:
            self.filename = filename
            
        self._setup_sqlite()

    def _setup_sqlite(self) -> None:
        """Initializes the SQLite database and ensures the schema is set up."""
        try:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.filename)), exist_ok=True)
            self.conn = sqlite3.connect(self.filename)
            self.cursor = self.conn.cursor()
            
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    dedup_key TEXT PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    about_job TEXT,
                    site TEXT,
                    url TEXT,
                    salary TEXT,
                    experience_required TEXT,
                    scraped_at TEXT,
                    job_id TEXT,
                    score INTEGER,
                    explanation TEXT,
                    ats_score TEXT
                )
            """)
            self.conn.commit()
            print(f"Initialized local SQLite database fallback at '{self.filename}'.")
        except Exception as e:
            print(f"[Error] Failed to initialize SQLite database '{self.filename}': {e}")

    def save_job(self, job: Job) -> Tuple[bool, dict]:
        """Saves or updates a job in the SQLite database with O(log n) deduplication using dedup_key."""
        title = (job.title or "").strip()
        company = (job.company or "").strip()
        location = (job.location or "").strip()
        about_job = (job.about_job or "").strip()
        dedup_key = job.dedup_key()

        # Step 1: Find existing job by dedup_key
        existing_doc = self.find_job_by_key(dedup_key)

        if existing_doc:
            # Merge site sources
            existing_sites = {s.strip() for s in existing_doc.get("site", "").split(",") if s.strip()}
            new_sites = job.site if isinstance(job.site, list) else [job.site]
            for s in new_sites:
                cleaned_site = s.strip()
                if cleaned_site:
                    existing_sites.add(cleaned_site)
            
            merged_sites_str = ", ".join(sorted(existing_sites))

            # Merge updates
            about_val = existing_doc.get("about_job") or about_job
            salary_val = existing_doc.get("salary") or job.salary
            url_val = existing_doc.get("url") or job.url
            
            score_val = job.score if (hasattr(job, "score") and job.score is not None) else existing_doc.get("score")
            explanation_val = job.explanation if (hasattr(job, "explanation") and job.explanation) else existing_doc.get("explanation")
            ats_score_val = job.ats_score if (hasattr(job, "ats_score") and job.ats_score is not None) else existing_doc.get("ats_score")

            try:
                self.cursor.execute(
                    """UPDATE jobs 
                       SET site = ?, about_job = ?, salary = ?, url = ?, score = ?, explanation = ?, ats_score = ?
                       WHERE dedup_key = ?""",
                    (merged_sites_str, about_val, salary_val, url_val, score_val, explanation_val, ats_score_val, dedup_key)
                )
                self.conn.commit()
            except Exception as e:
                print(f"[Warning] Failed to update job in SQLite database: {e}")

            # Return updated doc dict
            updated_doc = {
                "_id": dedup_key,
                "title": title,
                "company": company,
                "location": location,
                "about_job": about_val,
                "site": merged_sites_str,
                "url": url_val,
                "salary": salary_val,
                "experience_required": job.experience_required or existing_doc.get("experience_required"),
                "scraped_at": job.scraped_at.isoformat() if isinstance(job.scraped_at, datetime) else job.scraped_at,
                "job_id": job.job_id or existing_doc.get("job_id"),
                "score": score_val,
                "explanation": explanation_val,
                "ats_score": ats_score_val
            }
            return False, updated_doc
        else:
            # Insert new job
            site_str = ", ".join(job.site) if isinstance(job.site, list) else job.site
            job_dict = job.to_dict()
            try:
                self.cursor.execute(
                    """INSERT INTO jobs (dedup_key, title, company, location, about_job, site, url, salary, experience_required, scraped_at, job_id, score, explanation, ats_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        dedup_key,
                        title,
                        company,
                        location,
                        about_job,
                        site_str,
                        job.url,
                        job.salary,
                        job.experience_required,
                        job_dict["scraped_at"],
                        job.job_id,
                        job.score,
                        job.explanation,
                        job.ats_score
                    )
                )
                self.conn.commit()
            except Exception as e:
                print(f"[Warning] Failed to insert job into SQLite database: {e}")

            job_dict["_id"] = dedup_key
            return True, job_dict

    def find_job_by_key(self, dedup_key: str) -> dict:
        """Finds a job by its deduplication key in the SQLite database."""
        try:
            self.cursor.execute(
                "SELECT dedup_key, title, company, location, about_job, site, url, salary, experience_required, scraped_at, job_id, score, explanation, ats_score FROM jobs WHERE dedup_key = ?",
                (dedup_key,)
            )
            row = self.cursor.fetchone()
            if row:
                return {
                    "_id": row[0],
                    "title": row[1],
                    "company": row[2],
                    "location": row[3],
                    "about_job": row[4],
                    "site": row[5],
                    "url": row[6],
                    "salary": row[7],
                    "experience_required": row[8],
                    "scraped_at": row[9],
                    "job_id": row[10],
                    "score": row[11],
                    "explanation": row[12],
                    "ats_score": row[13]
                }
        except Exception as e:
            print(f"[Warning] Failed to fetch job from SQLite database: {e}")
        return None

    def get_all_jobs(self) -> list:
        """Returns all jobs stored in the SQLite database."""
        jobs_list = []
        try:
            self.cursor.execute(
                "SELECT dedup_key, title, company, location, about_job, site, url, salary, experience_required, scraped_at, job_id, score, explanation, ats_score FROM jobs"
            )
            rows = self.cursor.fetchall()
            for row in rows:
                jobs_list.append({
                    "_id": row[0],
                    "title": row[1],
                    "company": row[2],
                    "location": row[3],
                    "about_job": row[4],
                    "site": row[5],
                    "url": row[6],
                    "salary": row[7],
                    "experience_required": row[8],
                    "scraped_at": row[9],
                    "job_id": row[10],
                    "score": row[11],
                    "explanation": row[12],
                    "ats_score": row[13]
                })
        except Exception as e:
            print(f"[Warning] Failed to retrieve all jobs from SQLite database: {e}")
        return jobs_list

    def close(self) -> None:
        """Closes connection to SQLite database."""
        try:
            self.conn.close()
            print("SQLite database connection closed.")
        except Exception as e:
            print(f"Warning: error closing SQLite connection: {e}")
