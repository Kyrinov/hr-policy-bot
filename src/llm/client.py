from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import ollama

from src.config import get_config

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        num_predict: int | None = None,
        auth_header: str | None = None,
    ) -> None:
        self._config = get_config()
        self._model = model or self._config.model.name
        self._host = host
        self._num_predict = num_predict
        self._has_auth_header = auth_header is not None
        headers = {"Authorization": auth_header} if auth_header else None
        self._client = ollama.AsyncClient(host=host, headers=headers)

    def _options(self) -> dict[str, float | int]:
        options: dict[str, float | int] = {
            "temperature": self._config.model.temperature,
            "top_p": self._config.model.top_p,
            "num_ctx": self._config.model.num_ctx,
        }
        if self._num_predict is not None:
            options["num_predict"] = self._num_predict
        return options

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
            think=self._config.model.think,
        )
        return response.message.content or ""

    async def unload(self, model: str | None = None) -> None:
        """Ask Ollama to unload the model used by this client."""
        await self._client.generate(
            model=model or self._model,
            prompt="",
            keep_alive=0,
        )

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
            think=self._config.model.think,
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
            "host": self._host or "default",
            "auth_configured": self._has_auth_header,
            "model_available": model_available,
            "models": model_names,
        }


_orchestrator_client: OllamaClient | None = None
_specialist_client: OllamaClient | None = None


def get_client() -> OllamaClient:
    """Return the singleton orchestrator Ollama client."""
    return get_orchestrator_client()


def get_orchestrator_client() -> OllamaClient:
    """Return the singleton client for the 31B orchestrator runtime."""
    global _orchestrator_client
    if _orchestrator_client is None:
        config = get_config()
        _orchestrator_client = OllamaClient(
            model=config.model.name,
            host=config.model.orchestrator_host,
            num_predict=config.model.orchestrator_num_predict,
            auth_header=config.model.orchestrator_auth_header,
        )
    return _orchestrator_client


def get_specialist_client() -> OllamaClient:
    """Return the singleton client for the E4B specialist runtime."""
    global _specialist_client
    if _specialist_client is None:
        config = get_config()
        _specialist_client = OllamaClient(
            model=config.model.specialist_name,
            host=config.model.specialist_host,
            num_predict=config.model.specialist_num_predict,
            auth_header=config.model.specialist_auth_header,
        )
    return _specialist_client
