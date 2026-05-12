from __future__ import annotations

import abc
import logging
from typing import Any

from src.models.schemas import SpecialistResponse

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """Base interface for all agent types."""

    @property
    @abc.abstractmethod
    def agent_id(self) -> str:
        """Unique agent identifier."""
        ...

    @abc.abstractmethod
    async def process(self, query_text: str) -> SpecialistResponse:
        """Process a query and return a structured response."""
        pass


class GenericAgent(BaseAgent):
    """
    Generic agent implementation that can be configured for any domain.

    This class provides a base implementation that specialized agents
    can inherit from and extend with domain-specific logic.
    """

    def __init__(
        self,
        agent_id: str,
        display_name: str,
        domain_description: str,
        system_prompt: str,
    ) -> None:
        self._agent_id = agent_id
        self._display_name = display_name
        self._domain_description = domain_description
        self._system_prompt = system_prompt

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def domain_description(self) -> str:
        return self._domain_description

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    async def process(self, query_text: str) -> SpecialistResponse:
        """
        Base implementation - must be overridden by subclasses.

        Child classes should implement their own processing logic
        that may include policy document retrieval, LLM calls, etc.
        """
        raise NotImplementedError("Subclasses must implement process()")

    def build_prompt(self, query_text: str, policy_context: str = "") -> str:
        """
        Build a complete prompt for the LLM.

        Args:
            query_text: The user's query
            policy_context: Optional policy document excerpts to include

        Returns:
            Complete prompt string for LLM
        """
        prompt_parts = [
            self._system_prompt,
            f"\nUSER QUERY:\n{query_text}",
        ]

        if policy_context:
            prompt_parts.extend(
                [
                    "\nRELEVANT POLICY CONTENT:\n",
                    policy_context,
                ]
            )

        prompt_parts.append(
            "\n\nPlease provide your analysis in valid JSON format as specified in the output instructions."
        )

        return "\n\n".join(prompt_parts)
