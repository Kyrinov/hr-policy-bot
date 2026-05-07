from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import ollama

from src.config import get_config

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self) -> None:
        self._config = get_config()
        self._model = self._config.model.name
        self._client = ollama.AsyncClient()

    def _options(self) -> dict[str, float | int]:
        return {
            "temperature": self._config.model.temperature,
            "top_p": self._config.model.top_p,
            "num_ctx": self._config.model.num_ctx,
        }

    async def chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> str:
        """Send a chat request to Ollama and return the response text."""
        response = await self._client.chat(
            model=model or self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=self._options(),
        )
        return response.message.content or ""

    async def stream_chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from Ollama. Yields text chunks as they arrive."""
        stream = await self._client.chat(
            model=model or self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=self._options(),
            stream=True,
        )
        async for chunk in stream:
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

    async def health_check(self) -> dict:
        """Verify Ollama is reachable and the configured model is available."""
        models = await self._client.list()
        model_names = [m.model for m in models.models if m.model]
        model_available = self._model in model_names
        return {
            "status": "ok" if model_available else "missing_model",
            "configured_model": self._model,
            "model_available": model_available,
            "models": model_names,
        }


_client: OllamaClient | None = None


def get_client() -> OllamaClient:
    """Return the singleton Ollama client."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
