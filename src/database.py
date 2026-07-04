from typing import Tuple
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

    def close(self) -> None:
        """Closes connection to MongoDB."""
        try:
            self.client.close()
        except Exception as e:
            print(f"Warning: error closing MongoDB connection: {e}")
