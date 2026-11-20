import os
import json
import time
import re
from datetime import datetime
from typing import Dict, Any, Tuple
from src.config import Config


class GoogleClient:
    """Google Gemini API client — same interface as ClaudeClient."""

    # Cumulative class-level cost metrics
    session_input_tokens = 0
    session_output_tokens = 0
    session_cost_usd = 0.0

    MODEL_MAPPING = {
        "gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
        "gemini-3.8-flash": "gemini-3.8-flash",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-1.5-flash": "gemini-1.5-flash",
    }

    DEFAULT_MODEL = "gemini-3.5-flash-lite"

    def __init__(self, api_key: str = None, model: str = None, max_budget: float = None):
        self.api_key = api_key or Config.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Google API key not found. Please set GOOGLE_API_KEY in your .env file."
            )

        model = model or self.DEFAULT_MODEL
        model_lower = model.lower().strip()
        # If model is not a Gemini model (e.g., default Claude model passed via CLI), fallback to DEFAULT_MODEL
        if "gemini" not in model_lower:
            self.model = self.DEFAULT_MODEL
        else:
            self.model = self.MODEL_MAPPING.get(model_lower, model_lower)

        # Pricing (per 1M tokens) — Gemini 3.5 Flash Lite defaults
        self.input_price_per_m = 0.075
        self.output_price_per_m = 0.30

        try:
            env_budget = os.getenv("MAX_BUDGET_USD")
            default_budget = float(env_budget) if env_budget else 2.0
        except ValueError:
            default_budget = 2.0

        self.max_budget = max_budget if max_budget is not None else default_budget

        # Initialize Google GenAI client
        from google import genai
        self._client = genai.Client(api_key=self.api_key, http_options={"api_version": "v1beta"})

    def check_budget(self):
        if GoogleClient.session_cost_usd >= self.max_budget:
            raise ValueError(
                f"[Budget Cap] Total Google API cost (${GoogleClient.session_cost_usd:.4f}) "
                f"has reached or exceeded the maximum budget limit of ${self.max_budget:.2f}. "
                "API execution stopped to control costing."
            )

    def _call_google_api(self, system_prompt: str, user_content: str, temperature: float = 0.3, max_tokens: int = 4000) -> Tuple[str, Dict[str, Any]]:
        """Calls Google Gemini API. Returns (text, usage_stats)."""
        self.check_budget()

        from google.genai import types

        max_retries = 6
        backoff = 2.0

        for attempt in range(max_retries):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                    ),
                )

                text_response = response.text

                # Extract token usage
                usage = response.usage_metadata
                input_tokens = usage.prompt_token_count or 0
                output_tokens = usage.candidates_token_count or 0

                cost_usd = ((input_tokens / 1_000_000.0) * self.input_price_per_m) + \
                           ((output_tokens / 1_000_000.0) * self.output_price_per_m)

                GoogleClient.session_input_tokens += input_tokens
                GoogleClient.session_output_tokens += output_tokens
                GoogleClient.session_cost_usd += cost_usd

                usage_stats = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "cost_usd": cost_usd,
                }

                return text_response, usage_stats

            except Exception as e:
                err_str = str(e).lower()

                # 1. Model deprecation or 404 NOT_FOUND fallback to stable model
                if ("404" in err_str or "not_found" in err_str or "no longer available" in err_str) and self.model != "gemini-3.5-flash-lite":
                    print(f"    [Model Fallback] Model '{self.model}' is deprecated/unavailable. Falling back to 'gemini-3.5-flash-lite'...")
                    self.model = "gemini-3.5-flash-lite"
                    continue

                # 2. Server 503 high demand spike fallback
                if ("503" in err_str or "high demand" in err_str or "unavailable" in err_str) and self.model != "gemini-3.5-flash-lite":
                    print(f"    [Model Fallback] Model '{self.model}' is experiencing high demand (503). Falling back to 'gemini-3.5-flash-lite'...")
                    self.model = "gemini-3.5-flash-lite"
                    continue

                # 3. Rate limiting (429 / resource_exhausted / quota)
                if "429" in err_str or "resource_exhausted" in err_str or "rate" in err_str or "quota" in err_str:
                    if attempt < max_retries - 1:
                        # Extract 'retry after Xs' if specified by Google
                        wait_seconds = backoff
                        retry_match = re.search(r'retry after (\d+(?:\.\d+)?)s', err_str)
                        if retry_match:
                            wait_seconds = max(float(retry_match.group(1)) + 1.0, wait_seconds)
                        print(f"    [Rate Limit] Google API 429/Resource Exhausted. Retrying in {wait_seconds:.1f}s (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(wait_seconds)
                        backoff = min(backoff * 2.0, 60.0)
                        continue

                # 4. General network / API error
                if attempt < max_retries - 1:
                    print(f"    [Warning] Google API call failed: {e}. Retrying in {backoff}s (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, 60.0)
                else:
                    raise e

        raise RuntimeError("Google API request failed after all retries.")

    # ---------- same public methods as ClaudeClient ----------

    def get_match_score(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        job_info = (
            f"Title: {job_details.get('title', 'N/A')}\n"
            f"Company: {job_details.get('company', 'N/A')}\n"
            f"Location: {job_details.get('location', 'N/A')}\n"
            f"Salary: {job_details.get('salary', 'N/A')}\n"
            f"Description/Details: {job_details.get('about_job', 'N/A')}\n"
            f"Site: {job_details.get('site', 'N/A')}"
        )

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
            '{\n  "score": <integer from 0 to 10>,\n  "explanation": "<brief, 1-2 sentence explanation of the match score>"\n}'
        )

        user_content = (
            f"Here is the candidate's CV:\n---START CV---\n{cv_text}\n---END CV---\n\n"
            f"Here is the job posting details:\n---START JOB---\n{job_info}\n---END JOB---"
        )

        text_response, usage_stats = self._call_google_api(system_prompt, user_content, temperature=0.2)
        data = self._parse_json(text_response)

        score = data.get("score", 0)
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 0

        return {
            "score": score,
            "explanation": data.get("explanation", "No explanation provided."),
            "usage": usage_stats,
        }

    def get_tailored_cv_data(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
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
            '{\n'
            '  "contact_info": { "name": "", "email": "", "phone": "", "linkedin": "", "github": "", "location": "" },\n'
            '  "professional_summary": "",\n'
            '  "skills": { "technical_skills": [], "tools_and_technologies": [], "soft_skills": [] },\n'
            '  "work_experience": [{ "company": "", "role": "", "location": "", "start_date": "", "end_date": "", "achievements": [] }],\n'
            '  "projects": [{ "title": "", "technologies": "", "description": "" }],\n'
            '  "education": [{ "institution": "", "degree": "", "major": "", "graduation_year": "" }],\n'
            '  "certifications": []\n'
            '}'
        )
        user_content = f"Candidate's original CV text:\n{cv_text}\n\nJob details:\n{job_info}"

        text_response, usage_stats = self._call_google_api(system_prompt, user_content, temperature=0.3)
        data = json.loads(self._clean_json_text(text_response))
        return {"data": data, "usage": usage_stats}

    def get_tailored_cl_data(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        current_date = datetime.now().strftime("%B %d, %Y")
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
            '{\n'
            f'  "recipient_name": "Hiring Manager or Recruitment Team",\n'
            f'  "company_name": "Company Name",\n'
            f'  "date": "{current_date}",\n'
            '  "subject": "Application for [Job Title] - [Candidate Name]",\n'
            '  "salutation": "Dear Hiring Manager,",\n'
            '  "opening_paragraph": "",\n'
            '  "body_paragraphs": [],\n'
            '  "closing_paragraph": "",\n'
            '  "sign_off": "Sincerely,",\n'
            '  "sender_name": "Candidate\'s Full Name"\n'
            '}'
        )
        user_content = f"Candidate's original CV text:\n{cv_text}\n\nJob details:\n{job_info}"

        text_response, usage_stats = self._call_google_api(system_prompt, user_content, temperature=0.3)
        data = json.loads(self._clean_json_text(text_response))
        data["date"] = current_date
        return {"data": data, "usage": usage_stats}

    def get_tailored_ats_score(self, cv_data: dict, job_details: dict) -> Dict[str, Any]:
        cv_str = json.dumps(cv_data, indent=2, ensure_ascii=False)
        job_info = f"Title: {job_details.get('title', 'N/A')}\nCompany: {job_details.get('company', 'N/A')}\nDescription: {job_details.get('about_job', 'N/A')}"

        system_prompt = (
            "You are an ATS (Applicant Tracking System) scanner simulator.\n"
            "Your task is to analyze the provided tailored CV against the job description and compute a realistic, objective ATS match score.\n"
            "The match score must be an integer between 0 and 100 representing the match percentage.\n"
            'Format the output as a valid JSON object with a single key \'ats_score\' containing the integer (e.g., 92). Do not include any other text or markdown formatting.'
        )
        user_content = f"Tailored CV:\n{cv_str}\n\nJob details:\n{job_info}"

        text_response, usage_stats = self._call_google_api(system_prompt, user_content, temperature=0.1)
        data = self._parse_json(text_response)
        score_val = data.get("ats_score", 0)

        return {"ats_score": f"{score_val}%", "usage": usage_stats}

    # ---------- helpers ----------

    @staticmethod
    def _clean_json_text(text: str) -> str:
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        return clean.strip()

    @staticmethod
    def _parse_json(text: str) -> dict:
        clean = GoogleClient._clean_json_text(text)
        try:
            return json.loads(clean)
        except Exception:
            data = {}
            score_match = re.search(r'"score"\s*:\s*(\d+)', clean)
            exp_match = re.search(r'"explanation"\s*:\s*"([^"]+)"', clean)
            ats_match = re.search(r'"ats_score"\s*:\s*(\d+)', clean)
            if score_match:
                data["score"] = int(score_match.group(1))
            if exp_match:
                data["explanation"] = exp_match.group(1)
            if ats_match:
                data["ats_score"] = int(ats_match.group(1))
            return data
