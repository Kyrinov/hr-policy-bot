from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator

from openai import AsyncOpenAI

from src.config import get_config

logger = logging.getLogger(__name__)

_VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8001/v1")
_VLLM_MODEL = os.environ.get("VLLM_MODEL", "solidrust/Gemma-4-31B-Instruct-AWQ")


class VLLMClient:
    def __init__(self) -> None:
        self._config = get_config()
        self._model = os.environ.get("VLLM_MODEL", _VLLM_MODEL)
        self._client = AsyncOpenAI(base_url=_VLLM_BASE_URL, api_key="none")

    async def chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> str:
        """Send a chat request to vLLM and return the response text."""
        response = await self._client.chat.completions.create(
            model=model or self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._config.model.temperature,
            top_p=self._config.model.top_p,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    async def stream_chat(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from vLLM. Yields text chunks as they arrive."""
        stream = await self._client.chat.completions.create(
            model=model or self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._config.model.temperature,
            top_p=self._config.model.top_p,
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content or ""
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


_client: VLLMClient | None = None


def get_client() -> VLLMClient:
    """Return the singleton vLLM client."""
    global _client
    if _client is None:
        _client = VLLMClient()
    return _client
