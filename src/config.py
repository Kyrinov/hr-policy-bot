from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelConfig(BaseModel):
    name: str = "gemma4:26b"
    temperature: float = 0.2
    num_ctx: int = 32768
    top_p: float = 0.9


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class CacheConfig(BaseModel):
    ttl_hours: int = 168
    max_size_mb: int = 500


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/system.log"


class AppConfig(BaseModel):
    model: ModelConfig = ModelConfig()
    server: ServerConfig = ServerConfig()
    cache: CacheConfig = CacheConfig()
    logging: LoggingConfig = LoggingConfig()


def _load_config(path: Path) -> AppConfig:
    with open(path) as f:
        data = yaml.safe_load(f)

    # Environment variable overrides for sensitive/deployment values
    if model_name := os.environ.get("OLLAMA_MODEL"):
        data.setdefault("model", {})["name"] = model_name
    if host := os.environ.get("SERVER_HOST"):
        data.setdefault("server", {})["host"] = host
    if port := os.environ.get("SERVER_PORT"):
        data.setdefault("server", {})["port"] = int(port)

    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_config(config_path: str = "config.yaml") -> AppConfig:
    """Return the application configuration, loaded once and cached."""
    path = Path(config_path)
    if not path.is_absolute():
        # Resolve relative to project root (two levels up from this file)
        path = Path(__file__).parent.parent / config_path
    return _load_config(path)
