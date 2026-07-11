import os
import time
from typing import TypedDict, Dict, Any
from langgraph.graph import StateGraph, START, END
from playwright.sync_api import sync_playwright

from src.apply.profile_manager import check_and_setup_profile
from src.apply.form_filler import FormFiller

class ApplyState(TypedDict):
    url: str
    profile: Dict[str, Any]
    filled_successfully: bool
    status: str

def check_profile_node(state: ApplyState) -> Dict[str, Any]:
    """Node to verify and setup candidate profile details."""
    profile = check_and_setup_profile()
    # Merge initial state profile overrides (like custom tailored resume path)
    if "profile" in state:
        for k, v in state["profile"].items():
            if v:
                profile[k] = v
    return {"profile": profile, "status": "Profile verified"}

def fill_form_node(state: ApplyState) -> Dict[str, Any]:
    """Node that launches Playwright and populates form fields."""
    url = state["url"]
    profile = state["profile"]
    filled = False
    
    print("\n" + "=" * 50)
    print(f"LAUNCHING BROWSER AUTOMATION FOR URL:\n{url}")
    print("=" * 50)
    
    from src.config import Config
    import json
    
    # Resolve cookies/session data based on target portal
    user_data_dir = None
    storage_state = None
    user_agent = None

    if "linkedin.com" in url:
        user_data_dir = os.path.abspath("./playwright_linkedin_session")
        user_agent = Config.LINKEDIN_USER_AGENT
        if Config.LINKEDIN_STORAGE_STATE and Config.LINKEDIN_STORAGE_STATE.strip():
            try:
                storage_state = json.loads(Config.LINKEDIN_STORAGE_STATE)
            except Exception:
                pass
    elif "glassdoor.com" in url:
        user_data_dir = os.path.abspath("./playwright_glassdoor_session")
        user_agent = Config.GLASSDOOR_USER_AGENT
    elif "indeed.com" in url:
        user_data_dir = os.path.abspath("./playwright_indeed_session")

    with sync_playwright() as p:
        try:
            context = None
            browser = None
            
            # Launch with active session if available
            if storage_state:
                print("[Automation] Loading LinkedIn storage state from environment config...")
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(
                    storage_state=storage_state,
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
            elif user_data_dir and os.path.exists(user_data_dir):
                print(f"[Automation] Using persistent session directory: {user_data_dir}")
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1280, "height": 800}
                )
            else:
                print("[Automation] Launching clean browser session (No active session found)...")
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800}
                )

            page = context.pages[0] if context.pages else context.new_page()
            
            print(f"[Automation] Navigating to target portal...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            
            filler = FormFiller()
            filled = filler.fill_form(page, profile)
            
            if filled:
                print("\n" + "=" * 60)
                print("FORM POPULATED SUCCESSFULLY. Awaiting human verification to click Submit.")
                print("=" * 60)
                # Keep the browser open for human interaction
                input("\n>>> Please review the form, click Submit manually, and then press [Enter] here to finish...")
            else:
                print("[Error] Failed to populate form fields.")
                
            if browser:
                browser.close()
            else:
                context.close()
        except Exception as e:
            print(f"[Automation Error] Browser automation failed: {e}")
            filled = False
            
    return {"filled_successfully": filled, "status": "Automation complete"}

def build_apply_graph():
    """Builds and compiles the application automation LangGraph."""
    workflow = StateGraph(ApplyState)
    
    # Add nodes
    workflow.add_node("check_profile", check_profile_node)
    workflow.add_node("fill_form", fill_form_node)
    
    # Define edges
    workflow.add_edge(START, "check_profile")
    workflow.add_edge("check_profile", "fill_form")
    workflow.add_edge("fill_form", END)
    
    return workflow.compile()
