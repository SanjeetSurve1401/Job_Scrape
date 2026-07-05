import os
import json
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
    """Local JSON file persistent database fallback when MongoDB is not available."""
    def __init__(self, filename: str = "scraped_jobs.json"):
        self.filename = filename
        self.jobs = {}
        self.load_from_file()

    def load_from_file(self) -> None:
        """Loads existing jobs from the JSON database file at startup."""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for job_doc in data:
                        title = job_doc.get("title", "")
                        company = job_doc.get("company", "")
                        location = job_doc.get("location", "")
                        
                        # Compute dedup_key dynamically
                        normalized = f"{title.strip().lower()}|{company.strip().lower()}|{location.strip().lower()}"
                        import hashlib
                        dedup_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                        self.jobs[dedup_key] = job_doc
                print(f"Loaded {len(self.jobs)} existing jobs from local database '{self.filename}'.")
            except Exception as e:
                print(f"[Warning] Failed to load local database '{self.filename}': {e}")

    def save_job(self, job: Job) -> Tuple[bool, dict]:
        """Deduplicates and saves job locally."""
        title = (job.title or "").strip()
        company = (job.company or "").strip()
        location = (job.location or "").strip()
        about_job = (job.about_job or "").strip()

        dedup_key = job.dedup_key()
        existing_job = self.jobs.get(dedup_key)

        if existing_job:
            # Merge site sources
            existing_sites = {s.strip() for s in existing_job.get("site", "").split(",") if s.strip()}
            new_sites = job.site if isinstance(job.site, list) else [job.site]
            for s in new_sites:
                cleaned_site = s.strip()
                if cleaned_site:
                    existing_sites.add(cleaned_site)
            
            merged_sites_str = ", ".join(sorted(existing_sites))
            existing_job["site"] = merged_sites_str

            # Fill in missing fields from the new source
            if not existing_job.get("about_job") and about_job:
                existing_job["about_job"] = about_job
            if not existing_job.get("salary") and job.salary:
                existing_job["salary"] = job.salary
            if not existing_job.get("url") and job.url:
                existing_job["url"] = job.url
            if hasattr(job, "score") and job.score is not None:
                existing_job["score"] = job.score
            if hasattr(job, "explanation") and job.explanation:
                existing_job["explanation"] = job.explanation

            return False, existing_job
        else:
            job_dict = job.to_dict()
            job_dict["title"] = title
            job_dict["company"] = company
            job_dict["location"] = location
            job_dict["about_job"] = about_job
            job_dict["_id"] = dedup_key
            self.jobs[dedup_key] = job_dict
            return True, job_dict

    def find_job_by_key(self, dedup_key: str) -> dict:
        """Finds a job by its deduplication key in local database."""
        return self.jobs.get(dedup_key)

    def get_all_jobs(self) -> list:
        """Returns all jobs stored in memory."""
        return list(self.jobs.values())

    def close(self) -> None:
        pass
