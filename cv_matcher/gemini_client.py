import os
import requests
import json
from typing import Dict, Any
from src.config import Config

class GeminiClient:
    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        # Load API key from parameter, config, or environment variable
        self.api_key = api_key or Config.GEMINI_API or os.getenv("GEMINI_API")
        if not self.api_key:
            raise ValueError(
                "Gemini API key not found. Please set GEMINI_API in your .env file."
            )
        self.model = model
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    def get_match_score(self, cv_text: str, job_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends the CV text and job details to Gemini and asks it to score the match.
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
            "You must analyze the candidate's skills, experience, and background, and compare them with the job requirements.\n"
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

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": user_content
                        }
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {
                        "text": system_prompt
                    }
                ]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2
            }
        }

        headers = {
            "Content-Type": "application/json"
        }

        import time
        max_retries = 5
        backoff = 2.0

        for attempt in range(max_retries):
            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=30)
                
                # Check for rate limiting
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        print(f"    [Rate Limit] Hit 429 (Too Many Requests). Retrying in {backoff}s (attempt {attempt+1}/{max_retries})...")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                
                response.raise_for_status()
                res_json = response.json()
                
                # Extract text from response
                text_response = res_json['candidates'][0]['content']['parts'][0]['text']
                
                # Clean JSON markdown blocks if present
                clean_text = text_response.strip()
                if clean_text.startswith("```json"):
                    clean_text = clean_text[7:]
                elif clean_text.startswith("```"):
                    clean_text = clean_text[3:]
                if clean_text.endswith("```"):
                    clean_text = clean_text[:-3]
                clean_text = clean_text.strip()
                
                data = json.loads(clean_text)
                
                # Extract score and explanation
                score = data.get("score", 0)
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    try:
                        score = int(float(score))
                    except (ValueError, TypeError):
                        score = 0
                        
                return {
                    "score": score,
                    "explanation": data.get("explanation", "No explanation provided.")
                }
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"    [Warning] Request failed: {e}. Retrying in {backoff}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    return {
                        "score": 0,
                        "explanation": f"API request failed or failed to parse after {max_retries} attempts: {str(e)}"
                    }
