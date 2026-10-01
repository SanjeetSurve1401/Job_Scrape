import os
from src.config import Config

class OpenRouterClient:
    def __init__(self, api_key: str = None, model: str = "openrouter/free"):
        self.api_key = api_key or Config.OPENROUTER_API or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API")
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key not found. Please set OPENROUTER_API_KEY in your .env file."
            )
        self.model = model
        self.url = "https://openrouter.ai/api/v1/chat/completions"
