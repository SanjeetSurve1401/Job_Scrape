import os
import requests
import json
import time
import re
from typing import Dict, Any, Tuple
from src.config import Config

def accumulate_job_tokens(job_dict: dict, usage: dict):
    """
    Accumulates token usage and costs into a job's metadata.
    Handles None or missing dictionary values gracefully.
    """
    if not job_dict or not isinstance(job_dict, dict):
        return
    current_tokens = job_dict.get("tokens_consumed")
    if not isinstance(current_tokens, dict):
        current_tokens = {}
    
    input_tokens = current_tokens.get("input_tokens", 0) + usage.get("input_tokens", 0)
    output_tokens = current_tokens.get("output_tokens", 0) + usage.get("output_tokens", 0)
    total_tokens = current_tokens.get("total_tokens", 0) + usage.get("total_tokens", 0)
    cost_usd = round(current_tokens.get("cost_usd", 0.0) + usage.get("cost_usd", 0.0), 6)
    
    job_dict["tokens_consumed"] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd
    }

class ClaudeClient:
    # Cumulative class-level cost metrics
    session_input_tokens = 0
    session_output_tokens = 0
    session_cost_usd = 0.0

    # Model mapping to handle various requested names
    MODEL_MAPPING = {
        "claude haiku 4.5": "claude-haiku-4-5-20251001",
        "claude-haiku-4-5": "claude-haiku-4-5-20251001",
        "claude-haiku-4.5": "claude-haiku-4-5-20251001",
        "claude-3-5-haiku": "claude-3-5-haiku-20241022",
        "claude-3-5-haiku-latest": "claude-3-5-haiku-20241022",
        "claude-3-5-haiku-20241022": "claude-3-5-haiku-20241022"
    }

    def __init__(self, api_key: str = None, model: str = "claude-haiku-4-5-20251001", max_budget: float = None):
        self.api_key = api_key or Config.CLAUDE_API or os.getenv("CLAUDE_API") or os.getenv("CLAUDE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Claude API key not found. Please set CLAUDE_API or CLAUDE_API_KEY in your .env file."
            )
        
        # Normalize model name
        model_lower = model.lower().strip()
        self.model = self.MODEL_MAPPING.get(model_lower, model_lower if "claude" in model_lower else "claude-haiku-4-5-20251001")
        self.url = "https://api.anthropic.com/v1/messages"

        # Set dynamic pricing based on model name
        if "haiku-4-5" in self.model or "haiku-4.5" in self.model:
            self.input_price_per_m = 1.00
            self.output_price_per_m = 5.00
        else:
            self.input_price_per_m = 0.80
            self.output_price_per_m = 4.00
        
        # Load budget from env
        try:
            env_budget = os.getenv("MAX_BUDGET_USD")
            default_budget = float(env_budget) if env_budget else 2.0
        except ValueError:
            default_budget = 2.0
            
        self.max_budget = max_budget if max_budget is not None else default_budget

    def check_budget(self):
        """Checks if the cumulative session cost exceeds the allowed budget."""
        if ClaudeClient.session_cost_usd >= self.max_budget:
            raise ValueError(
                f"[Budget Cap] Total Claude API cost (${ClaudeClient.session_cost_usd:.4f}) "
                f"has reached or exceeded the maximum budget limit of ${self.max_budget:.2f}. "
                "API execution stopped to control costing."
            )

    def _call_claude_api(self, system_prompt: str, user_content: str, temperature: float = 0.3, max_tokens: int = 4000) -> Tuple[str, Dict[str, Any]]:
        """
        Executes a call to Anthropic Messages API.
        Tracks and adds tokens and cost to the cumulative class-level trackers.
        Returns the assistant's response text and a usage statistics dictionary.
        """
        self.check_budget()

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_content}
            ],
            "temperature": temperature
        }

        max_retries = 5
        backoff = 2.0

        for attempt in range(max_retries):
            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=60)
                
                # Check for rate limiting
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        print(f"    [Rate Limit] Hit 429 (Too Many Requests). Retrying in {backoff}s...")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                
                response.raise_for_status()
                res_json = response.json()
                
                # Extract text response
                text_response = res_json["content"][0]["text"]
                
                # Extract token usage
                usage = res_json.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                
                # Calculate cost
                cost_usd = ((input_tokens / 1_000_000.0) * self.input_price_per_m) + \
                           ((output_tokens / 1_000_000.0) * self.output_price_per_m)
                
                # Accumulate session cost
                ClaudeClient.session_input_tokens += input_tokens
                ClaudeClient.session_output_tokens += output_tokens
                ClaudeClient.session_cost_usd += cost_usd
                
                usage_stats = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "cost_usd": cost_usd
                }
                
                return text_response, usage_stats
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"    [Warning] Claude API call failed: {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise e

        raise RuntimeError("Claude API request failed after all retries.")

    def get_match_score(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends the CV text and job details to Claude and asks it to score the match.
        Returns a dictionary with 'score' (int) and 'explanation' (str).
        """
        job_info = f"""
Title: {job_details.get('title', 'N/A')}
Company: {job_details.get('company', 'N/A')}
Location: {job_details.get('location', 'N/A')}
Salary: {job_details.get('salary', 'N/A')}
Description/Details: {job_details.get('about_job', 'N/A')}
Site: {job_details.get('site', 'N/A')}
"""
        
        system_prompt = (
            "You are an expert technical recruiter. Your task is to evaluate if a candidate's CV "
            "is a good match for a given job posting.\n"
            "Analyze the candidate's skills, experience, and background, and compare them with the job requirements.\n"
            "Provide a score from 0 to 10 where:\n"
            "- 0-3: Poor match or completely irrelevant.\n"
            "- 4-6: Fair match (some relevant skills, but missing key experience or requirements).\n"
            "- 7-8: Good match (meets most requirements, has matching skills).\n"
            "- 9-10: Perfect match (meets all or almost all requirements, highly qualified).\n\n"
            "You must return the response in JSON format with exactly the following structure:\n"
            "{\n"
            "  \"score\": <integer from 0 to 10>,\n"
            "  \"explanation\": \"<brief, 1-2 sentence explanation of the match score>\"\n"
            "}"
        )

        user_content = (
            f"Here is the candidate's CV:\n---START CV---\n{cv_text}\n---END CV---\n\n"
            f"Here is the job posting details:\n---START JOB---\n{job_info}\n---END JOB---"
        )

        text_response, usage_stats = self._call_claude_api(system_prompt, user_content, temperature=0.2)
        
        # Clean JSON markdown blocks if present
        clean_text = text_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        try:
            data = json.loads(clean_text)
        except Exception:
            # Simple fallback parser if response is not valid JSON
            data = {}
            score_match = re.search(r'"score"\s*:\s*(\d+)', clean_text)
            exp_match = re.search(r'"explanation"\s*:\s*"([^"]+)"', clean_text)
            data["score"] = int(score_match.group(1)) if score_match else 0
            data["explanation"] = exp_match.group(1) if exp_match else "Failed to parse JSON."

        score = data.get("score", 0)
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 0
            
        return {
            "score": score,
            "explanation": data.get("explanation", "No explanation provided."),
            "usage": usage_stats
        }

    def get_tailored_cv_data(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rewrites and tailors CV data to match a specific job description.
        Returns a dictionary representing the tailored CV.
        """
        job_info = f"Title: {job_details.get('title', 'N/A')}\nCompany: {job_details.get('company', 'N/A')}\nDescription: {job_details.get('about_job', 'N/A')}"
        system_prompt = (
            "You are an expert technical recruiter and resume writer.\n"
            "Your task is to rewrite and tailor the candidate's CV to maximize its ATS match and relevance for the given job posting.\n"
            "Follow these strict rules:\n"
            "1. Do NOT invent or fabricate any experience, skills, projects, certifications, or achievements. Doing so is fraud.\n"
            "2. Only rephrase, reorganize, and emphasize information already present in the original CV.\n"
            "3. Incorporate relevant keywords, skills, and technologies from the job description ONLY where they genuinely match the candidate's existing experience.\n"
            "4. Prioritize and highlight the experience, projects, and skills that are most relevant to the target role.\n"
            "5. The output must be a valid JSON object matching the schema below. Do not include any other text, markdown formatting (no ```json), or comments.\n\n"
            "JSON Schema:\n"
            "{\n"
            "  \"contact_info\": {\n"
            "    \"name\": \"Candidate's full name\",\n"
            "    \"email\": \"Candidate's email\",\n"
            "    \"phone\": \"Candidate's phone number\",\n"
            "    \"linkedin\": \"Candidate's LinkedIn URL (if present)\",\n"
            "    \"github\": \"Candidate's GitHub URL (if present)\",\n"
            "    \"location\": \"Candidate's city/location\"\n"
            "  },\n"
            "  \"professional_summary\": \"A short, compelling, and tailored professional summary.\",\n"
            "  \"skills\": {\n"
            "    \"technical_skills\": [\"list of technical skills\"],\n"
            "    \"tools_and_technologies\": [\"list of tools and technologies\"],\n"
            "    \"soft_skills\": [\"list of soft skills/methodologies\"]\n"
            "  },\n"
            "  \"work_experience\": [\n"
            "    {\n"
            "      \"company\": \"Company name\",\n"
            "      \"role\": \"Job title / Role\",\n"
            "      \"location\": \"Company location\",\n"
            "      \"start_date\": \"Start date\",\n"
            "      \"end_date\": \"End date or Present\",\n"
            "      \"achievements\": [\n"
            "        \"Bullet point 1 detailing achievements and responsibilities\",\n"
            "        \"Bullet point 2...\"\n"
            "      ]\n"
            "    }\n"
            "  ],\n"
            "  \"projects\": [\n"
            "    {\n"
            "      \"title\": \"Project title\",\n"
            "      \"technologies\": \"Technologies used\",\n"
            "      \"description\": \"Project description tailored to highlight relevant skills\"\n"
            "    }\n"
            "  ],\n"
            "  \"education\": [\n"
            "    {\n"
            "      \"institution\": \"School/University name\",\n"
            "      \"degree\": \"Degree\",\n"
            "      \"major\": \"Major\",\n"
            "      \"graduation_year\": \"Year of graduation\"\n"
            "    }\n"
            "  ],\n"
            "  \"certifications\": [\"list of certifications\"]\n"
            "}"
        )
        user_content = f"Candidate's original CV text:\n{cv_text}\n\nJob details:\n{job_info}"
        
        text_response, usage_stats = self._call_claude_api(system_prompt, user_content, temperature=0.3)
        
        clean_text = text_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        data = json.loads(clean_text)
        return {
            "data": data,
            "usage": usage_stats
        }

    def get_tailored_cl_data(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates customized cover letter data.
        Returns a dictionary containing the cover letter parameters.
        """
        job_info = f"Title: {job_details.get('title', 'N/A')}\nCompany: {job_details.get('company', 'N/A')}\nDescription: {job_details.get('about_job', 'N/A')}"
        system_prompt = (
            "You are an expert career consultant.\n"
            "Write a professional, customized cover letter for the candidate applying to the given job posting.\n"
            "Follow these strict rules:\n"
            "1. Do NOT invent or fabricate any experience, skills, projects, certifications, or achievements. Only use facts present in the candidate's CV.\n"
            "2. Align the cover letter with the job requirements and highlight the candidate's most relevant qualifications and experiences.\n"
            "3. Keep the tone professional, persuasive, and engaging.\n"
            "4. Format the output as a valid JSON object matching the schema below. Do not include any other text, markdown formatting (no ```json), or comments.\n\n"
            "JSON Schema:\n"
            "{\n"
            "  \"recipient_name\": \"Hiring Manager or Recruitment Team\",\n"
            "  \"company_name\": \"Company Name\",\n"
            "  \"date\": \"Current Date (e.g., July 6, 2026)\",\n"
            "  \"subject\": \"Application for [Job Title] - [Candidate Name]\",\n"
            "  \"salutation\": \"Dear Hiring Manager,\",\n"
            "  \"opening_paragraph\": \"Introduction of the candidate, the role they are applying for, and why they are interested in the company.\",\n"
            "  \"body_paragraphs\": [\n"
            "    \"Paragraph highlighting matching experience and skills.\",\n"
            "    \"Paragraph discussing specific achievements or projects.\"\n"
            "  ],\n"
            "  \"closing_paragraph\": \"Summary of interest, call to action, and professional wrap-up.\",\n"
            "  \"sign_off\": \"Sincerely,\",\n"
            "  \"sender_name\": \"Candidate's Full Name\"\n"
            "}"
        )
        user_content = f"Candidate's original CV text:\n{cv_text}\n\nJob details:\n{job_info}"
        
        text_response, usage_stats = self._call_claude_api(system_prompt, user_content, temperature=0.3)
        
        clean_text = text_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        data = json.loads(clean_text)
        return {
            "data": data,
            "usage": usage_stats
        }

    def get_tailored_ats_score(self, cv_data: dict, job_details: dict) -> Dict[str, Any]:
        """
        Simulates an ATS scanner match score for tailored CV.
        Returns a dictionary containing the ATS score string and usage.
        """
        cv_str = json.dumps(cv_data, indent=2, ensure_ascii=False)
        job_info = f"Title: {job_details.get('title', 'N/A')}\nCompany: {job_details.get('company', 'N/A')}\nDescription: {job_details.get('about_job', 'N/A')}"
        
        system_prompt = (
            "You are an ATS (Applicant Tracking System) scanner simulator.\n"
            "Your task is to analyze the provided tailored CV against the job description and compute a realistic, objective ATS match score.\n"
            "The match score must be an integer between 0 and 100 representing the match percentage.\n"
            "Format the output as a valid JSON object with a single key 'ats_score' containing the integer (e.g., 92). Do not include any other text or markdown formatting."
        )
        user_content = f"Tailored CV:\n{cv_str}\n\nJob details:\n{job_info}"
        
        text_response, usage_stats = self._call_claude_api(system_prompt, user_content, temperature=0.1)
        
        clean_text = text_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        try:
            data = json.loads(clean_text)
            score_val = data.get("ats_score", 0)
        except Exception:
            score_match = re.search(r'"ats_score"\s*:\s*(\d+)', clean_text)
            score_val = int(score_match.group(1)) if score_match else 0
            
        return {
            "ats_score": f"{score_val}%",
            "usage": usage_stats
        }
