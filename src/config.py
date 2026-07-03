import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME = os.getenv("DB_NAME", "mongodbVSCodePlaygroundDB")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "jobs")
    GLASSDOOR_SESSION_PATH = os.getenv("GLASSDOOR_SESSION_PATH", "glassdoor_session.json")
    LINKEDIN_COOKIES_PATH = os.getenv("LINKEDIN_COOKIES_PATH", "linkedin_cookies.json")
