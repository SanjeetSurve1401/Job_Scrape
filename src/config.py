import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME = os.getenv("DB_NAME", "mongodbVSCodePlaygroundDB")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "jobs")
    GLASSDOOR_USER_AGENT = os.getenv("GLASSDOOR_USER_AGENT", "")
    GLASSDOOR_COOKIE = os.getenv("GLASSDOOR_COOKIE", "")
    GLASSDOOR_STORAGE_STATE = os.getenv("GLASSDOOR_STORAGE_STATE", "")
    GEMINI_API = os.getenv("GEMINI_API", "")
    GROQ_API = os.getenv("GROQ_API", "")
    OPENROUTER_API = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API", "")
    CLAUDE_API = os.getenv("CLAUDE_API") or os.getenv("CLAUDE_API_KEY", "")
    LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE", "")
    LINKEDIN_USER_AGENT = os.getenv("LINKEDIN_USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    LINKEDIN_STORAGE_STATE = os.getenv("LINKEDIN_STORAGE_STATE", "")
    INDEED_COOKIE = os.getenv("INDEED_COOKIE", "")
    INDEED_USER_AGENT = os.getenv("INDEED_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0")
    INDEED_STORAGE_STATE = os.getenv("INDEED_STORAGE_STATE", "")
