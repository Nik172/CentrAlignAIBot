"""
Abstract base for every tool the agent can use. Every concrete tool
implements the same execute(params) -> Observation contract, which is
what lets the orchestrator stay completely tool-agnostic.
"""
from abc import ABC, abstractmethod
from core.schemas import Observation


class Tool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    def execute(self, params: dict) -> Observation:
        """Execute the tool with given params, return a structured Observation."""
        ...

    def to_prompt_spec(self) -> dict:
        """Serializable description fed to the LLM so it knows this tool exists
        and how to call it."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }