"""
LLM client abstraction. Everything downstream (planner, decision engine,
error classifier, verifier) depends only on `LLMClient.structured_call`,
never on a specific provider. This is what lets us run in mock mode today
and swap in Gemini/Groq later with zero changes anywhere else.
"""
import json
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from config import config

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    @abstractmethod
    def structured_call(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        """Must return a validated instance of `schema`. Raises on failure."""
        ...


# ---------------------------------------------------------------------------
# Mock client — used when no real API keys are configured yet.
# ---------------------------------------------------------------------------

class MockLLMClient(LLMClient):
    def structured_call(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        print("\n[MockLLMClient] ⚠️  No real API key configured — returning placeholder response.")
        print(f"[MockLLMClient] Schema requested: {schema.__name__}")
        return self._build_placeholder(schema)

    def _build_placeholder(self, schema: type[T]) -> T:
        json_schema = schema.model_json_schema()
        placeholder = self._fill_from_schema(json_schema, json_schema.get("$defs", {}))
        return schema.model_validate(placeholder)

    def _fill_from_schema(self, schema: dict, defs: dict) -> any:
        schema_type = schema.get("type")
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            return self._fill_from_schema(defs[ref_name], defs)
        if "enum" in schema:
            return schema["enum"][0]
        if schema_type == "object" or "properties" in schema:
            props = schema.get("properties", {})
            return {k: self._fill_from_schema(v, defs) for k, v in props.items()}
        if schema_type == "array":
            return []
        if schema_type == "string":
            return "PLACEHOLDER"
        if schema_type == "boolean":
            return True
        if schema_type in ("integer", "number"):
            return 0
        return None


# ---------------------------------------------------------------------------
# Gemini client (new `google-genai` SDK — replaces deprecated
# `google-generativeai`, which had a known bug converting Pydantic schemas
# with Optional/default fields ("Unknown field for Schema: default").
# This SDK handles Optional/defaults correctly.
#
# Model names on the free tier shift over time, so we try a list of
# candidates and remember whichever one actually works for subsequent calls
# instead of hardcoding a single name that may 404.
# ---------------------------------------------------------------------------

class GeminiClient(LLMClient):
    CANDIDATE_MODELS = [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
    ]

    def __init__(self, api_key: str, model: str | None = None):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self._working_model: str | None = model

    def structured_call(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        from google.genai import types

        candidates = [self._working_model] if self._working_model else []
        candidates += [m for m in self.CANDIDATE_MODELS if m != self._working_model]

        last_error: Exception | None = None
        for model_name in candidates:
            if not model_name:
                continue
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
                self._working_model = model_name  # cache the working model
                return schema.model_validate_json(response.text)
            except Exception as e:
                print(f"[GeminiClient] model '{model_name}' failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All Gemini model candidates failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

class GroqClient(LLMClient):
    """
    Groq model names shift over time and availability varies by account/key,
    so we try a list of candidates (pulled from what's actually confirmed
    available on this key via /v1/models) and cache whichever one works for
    subsequent calls — same resilience pattern as GeminiClient.
    """
    CANDIDATE_MODELS = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3-32b",
    ]

    def __init__(self, api_key: str, model: str | None = None):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self._working_model: str | None = model

    def structured_call(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        schema_hint = json.dumps(schema.model_json_schema())
        candidates = [self._working_model] if self._working_model else []
        candidates += [m for m in self.CANDIDATE_MODELS if m != self._working_model]

        last_error: Exception | None = None
        for model_name in candidates:
            if not model_name:
                continue
            try:
                response = self.client.chat.completions.create(
                    model=model_name,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": f"{system_prompt}\n\nRespond ONLY with valid JSON matching this schema:\n{schema_hint}",
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                )
                self._working_model = model_name
                return schema.model_validate_json(response.choices[0].message.content)
            except Exception as e:
                print(f"[GroqClient] model '{model_name}' failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All Groq model candidates failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Fallback wrapper
# ---------------------------------------------------------------------------

class FallbackLLMClient(LLMClient):
    def __init__(self, clients: list[LLMClient]):
        assert clients, "FallbackLLMClient requires at least one client"
        self.clients = clients

    def structured_call(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        last_error: Exception | None = None
        for i, client in enumerate(self.clients):
            try:
                result = client.structured_call(system_prompt, user_prompt, schema)
                if i > 0:
                    print(f"[FallbackLLMClient] ✅ Recovered using backup provider: {type(client).__name__}")
                return result
            except Exception as e:
                print(f"[FallbackLLMClient] ⚠️  {type(client).__name__} unavailable ({e.__class__.__name__}) — trying next provider...")
                last_error = e
                continue
        raise RuntimeError(f"All LLM providers exhausted. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_client() -> LLMClient:
    if config.is_mock_mode:
        return MockLLMClient()

    clients: list[LLMClient] = []
    if config.has_real_gemini_key:
        clients.append(GeminiClient(config.GEMINI_API_KEY, config.GEMINI_MODEL))
    if config.has_real_groq_key:
        clients.append(GroqClient(config.GROQ_API_KEY, config.GROQ_MODEL))

    return FallbackLLMClient(clients) if len(clients) > 1 else clients[0]