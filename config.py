"""
Central configuration loader.
All environment-dependent values flow through here — no module outside this
file should touch os.environ directly. Makes it trivial to see, at a glance,
every external dependency the system has.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val


class Config:
    GEMINI_API_KEY: str = _get("GEMINI_API_KEY", "PLACEHOLDER_GEMINI_KEY")
    GROQ_API_KEY: str = _get("GROQ_API_KEY", "PLACEHOLDER_GROQ_KEY")

    GEMINI_MODEL: str = _get("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_MODEL: str = _get("GROQ_MODEL", "llama-3.3-70b-versatile")

    @property
    def has_real_gemini_key(self) -> bool:
        return not self.GEMINI_API_KEY.startswith("PLACEHOLDER")

    @property
    def has_real_groq_key(self) -> bool:
        return not self.GROQ_API_KEY.startswith("PLACEHOLDER")

    @property
    def is_mock_mode(self) -> bool:
        """
        If no real API keys are present at all, the system falls back to a
        deterministic MockLLMClient so the rest of the pipeline (orchestrator,
        tools, mock envs) can still be built, run, and demoed before real
        keys are added.
        """
        return not (self.has_real_gemini_key or self.has_real_groq_key)


config = Config()