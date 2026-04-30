from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import ollama

from src.config import get_config
from src.models.schemas import ModelConfig

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self) -> None:
        self._config = get_config()
        self._model = self._config.model.name
        self._client = ollama.AsyncClient()

    async def chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> str:
        """Send a chat request to Ollama and return the raw response text."""
        model_name = model or self._model
        response = await self._client.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=self._model_options(),
        )
        return response.message.content or ""

    async def stream_chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from Ollama. Yields chunks as they arrive."""
        model_name = model or self._model
        async for chunk in await self._client.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            stream=True,
            options=self._model_options(),
        ):
            content = chunk.message.content or ""
            if content:
                yield content

    async def chat_parsed(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> dict:
        """Send a chat request and attempt to parse the response as JSON."""
        raw = await self.chat(system_prompt, user_message, model)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response as JSON: %s", e)
            logger.debug("Raw response: %s", raw)
            return {"_raw": raw, "_parse_error": str(e)}

    def _model_options(self) -> dict:
        """Return model options from configuration."""
        return {
            "temperature": self._config.model.temperature,
            "num_ctx": self._config.model.num_ctx,
            "top_p": self._config.model.top_p,

        }


_client: OllamaClient | None = None


def get_client() -> OllamaClient:
    """Return the singleton Ollama client."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
