import operator
import os
from typing import Annotated, Dict, Any, List, TypedDict
from langgraph.graph import StateGraph, START, END

from src.config import Config
from src.models import Job
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.glassdoor import GlassdoorScraper
from src.verifier import JobVerifier
from src.database import DatabaseHandler, LocalDatabaseHandler
from src.tailor_cv.claude_client import ClaudeClient, accumulate_job_tokens

class ScraperState(TypedDict):
    role: str
    location: str
    experience: str
    limit: int
    groq_model: str
    cv_text: str
    sources: List[str]
    output_path: str
    raw_jobs: Annotated[List[Job], operator.add]
    verified_jobs: List[Job]
    processed_jobs_list: List[dict]
    summary_stats: dict
    start_offset: int

def scrape_linkedin_node(state: ScraperState) -> Dict[str, Any]:
    if "linkedin" not in state["sources"]:
        return {"raw_jobs": []}
    scraper = LinkedInScraper()
    jobs = scraper.scrape(state["role"], state["location"], state["experience"], limit=state["limit"], start_offset=state.get("start_offset", 0))
    return {"raw_jobs": jobs}

def scrape_indeed_node(state: ScraperState) -> Dict[str, Any]:
    if "indeed" not in state["sources"]:
        return {"raw_jobs": []}
    scraper = IndeedScraper()
    jobs = scraper.scrape(state["role"], state["location"], state["experience"], limit=state["limit"], start_offset=state.get("start_offset", 0))
    return {"raw_jobs": jobs}

def scrape_glassdoor_node(state: ScraperState) -> Dict[str, Any]:
    if "glassdoor" not in state["sources"]:
        return {"raw_jobs": []}
    scraper = GlassdoorScraper()
    jobs = scraper.scrape(state["role"], state["location"], state["experience"], limit=state["limit"], start_offset=state.get("start_offset", 0))
    return {"raw_jobs": jobs}

def verify_jobs_node(state: ScraperState) -> Dict[str, Any]:
    verifier = JobVerifier()
    raw_jobs = state.get("raw_jobs", [])
    verified = []
    seen_keys = set()
    
    print("\n[LangGraph Verify Node] Verifying scraped jobs...")
    for job in raw_jobs:
        if not job.title or not job.company:
            continue
            
        dedup_key = job.dedup_key()
        if dedup_key in seen_keys:
            continue
            
        if verifier.verify(job, state["role"], state["location"], state["experience"]):
            seen_keys.add(dedup_key)
            verified.append(job)
            
    print(f"[LangGraph Verify Node] Verified {len(verified)} jobs out of {len(raw_jobs)} raw jobs.")
    return {"verified_jobs": verified}

def score_jobs_node(state: ScraperState) -> Dict[str, Any]:
    cv_text = state.get("cv_text", "")
    verified_jobs = state.get("verified_jobs", [])
    processed_jobs = []
    
    client = None
    if cv_text and Config.CLAUDE_API and Config.CLAUDE_API.strip():
        try:
            client = ClaudeClient(model=state.get("groq_model", "claude-3-5-haiku-20241022"))
        except Exception as e:
            print(f"[LangGraph Score Node Error] Failed to initialize Claude Client: {e}")
            
    for job in verified_jobs:
        job_dict = job.to_dict()
        if client:
            print(f"  [Scoring API Call] '{job.title}' at {job.company}...")
            try:
                res = client.get_match_score(cv_text, job_dict)
                job_dict["score"] = res["score"]
                job_dict["explanation"] = res["explanation"]
                accumulate_job_tokens(job_dict, res["usage"])
                print(f"    -> Score: {res['score']}/10")
                
                # Respect rate limit
                import time
                time.sleep(2.0)
            except Exception as e:
                print(f"    -> Scoring failed: {e}")
                job_dict["score"] = 0
                job_dict["explanation"] = f"Scoring failed: {e}"
        else:
            job_dict["score"] = None
            job_dict["explanation"] = None
            
        processed_jobs.append(job_dict)
        
    return {"processed_jobs_list": processed_jobs}

def save_jobs_node(state: ScraperState) -> Dict[str, Any]:
    processed_jobs = state.get("processed_jobs_list", [])
    
    db = None
    if Config.MONGO_URI and Config.MONGO_URI.strip():
        try:
            print("[LangGraph Save Node] Connecting to MongoDB...")
            db = DatabaseHandler(
                uri=Config.MONGO_URI,
                db_name=Config.DB_NAME,
                collection_name=Config.COLLECTION_NAME
            )
            print("[LangGraph Save Node] Connected to MongoDB successfully.")
        except Exception as e:
            print(f"[LangGraph Save Node Warning] MongoDB connection failed ({e})")
            
    if db is None:
        output_file = state.get("output_path") or "jobs.json"
        print(f"[LangGraph Save Node] Using local in-memory storage (file: {output_file}).")
        db = LocalDatabaseHandler(filename=output_file)
        
    new_inserted = 0
    updated_count = 0
    saved_jobs_list = []
    
    for job_dict in processed_jobs:
        job_obj = Job(
            title=job_dict.get("title", ""),
            company=job_dict.get("company", ""),
            location=job_dict.get("location", ""),
            about_job=job_dict.get("about_job", ""),
            site=job_dict.get("site", []),
            url=job_dict.get("url", ""),
            salary=job_dict.get("salary"),
            job_id=job_dict.get("job_id", ""),
            experience_required=job_dict.get("experience_required")
        )
        if "score" in job_dict:
            job_obj.score = job_dict["score"]
        if "explanation" in job_dict:
            job_obj.explanation = job_dict["explanation"]
        if "tokens_consumed" in job_dict:
            job_obj.tokens_consumed = job_dict["tokens_consumed"]
            
        is_new, saved_doc = db.save_job(job_obj)
        if is_new:
            new_inserted += 1
        else:
            updated_count += 1
        saved_jobs_list.append(saved_doc)
        
    db.close()
    
    stats = {
        "total_raw": len(state.get("raw_jobs", [])),
        "total_verified": len(state.get("verified_jobs", [])),
        "new_inserted": new_inserted,
        "updated": updated_count
    }
    
    print(f"\n[LangGraph Save Node] Execution Stats: {stats}")
    return {"processed_jobs_list": saved_jobs_list, "summary_stats": stats}

def build_scraper_graph():
    workflow = StateGraph(ScraperState)
    
    # Add nodes
    workflow.add_node("scrape_linkedin", scrape_linkedin_node)
    workflow.add_node("scrape_indeed", scrape_indeed_node)
    workflow.add_node("scrape_glassdoor", scrape_glassdoor_node)
    workflow.add_node("verify_jobs", verify_jobs_node)
    workflow.add_node("score_jobs", score_jobs_node)
    workflow.add_node("save_jobs", save_jobs_node)
    
    # Parallel scraping
    workflow.add_edge(START, "scrape_linkedin")
    workflow.add_edge(START, "scrape_indeed")
    workflow.add_edge(START, "scrape_glassdoor")
    
    # Merge paths into verification
    workflow.add_edge("scrape_linkedin", "verify_jobs")
    workflow.add_edge("scrape_indeed", "verify_jobs")
    workflow.add_edge("scrape_glassdoor", "verify_jobs")
    
    # Sequential processing
    workflow.add_edge("verify_jobs", "score_jobs")
    workflow.add_edge("score_jobs", "save_jobs")
    workflow.add_edge("save_jobs", END)
    
    return workflow.compile()
