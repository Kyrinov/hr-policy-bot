from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelConfig(BaseModel):
    name: str = "gemma4:31b"
    specialist_name: str = "gemma4:e4b"
    orchestrator_host: str = "http://127.0.0.1:11436"
    specialist_host: str = "http://127.0.0.1:11435"
    orchestrator_auth_header: str | None = None
    specialist_auth_header: str | None = None
    temperature: float = 0.2
    num_ctx: int = 32768
    top_p: float = 0.9
    think: bool = False
    orchestrator_num_predict: int = 1800
    specialist_num_predict: int = 1000
    route_with_llm: bool = False


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class CacheConfig(BaseModel):
    ttl_hours: int = 168
    max_size_mb: int = 500


class StorageConfig(BaseModel):
    data_dir: str = "data"
    db_path: str | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/system.log"


class ParsingRuleConfig(BaseModel):
    enabled: bool = True
    section_ref_regex: str | None = None


class ParsingConfig(BaseModel):
    enabled: bool = True
    spacy_model: str = "en_core_web_sm"
    spacy_model_version: str = "3.7.1"
    query_entity_threshold: int = 2
    validate_mode_threshold: int = 5
    max_graph_results: int = 20
    warmup_on_startup: bool = False
    teacher_loop_enabled: bool = True
    validation_rules: dict[str, ParsingRuleConfig] = {
        "RULE-01": ParsingRuleConfig(enabled=True),
        "RULE-02": ParsingRuleConfig(enabled=True),
        "RULE-03": ParsingRuleConfig(
            enabled=True,
            section_ref_regex=r"(s\.\s*\d+(\.\d+)*|[Ss]ection\s+\d+(\.\d+)*|[Aa]rticle\s+\d+)",
        ),
        "RULE-04": ParsingRuleConfig(enabled=True),
        "RULE-05": ParsingRuleConfig(enabled=True),
    }


class AppConfig(BaseModel):
    model: ModelConfig = ModelConfig()
    server: ServerConfig = ServerConfig()
    cache: CacheConfig = CacheConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()
    parsing: ParsingConfig = ParsingConfig()


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_config(path: Path) -> AppConfig:
    with open(path) as f:
        data = yaml.safe_load(f)

    # Environment variable overrides for sensitive/deployment values
    if model_name := os.environ.get("OLLAMA_MODEL"):
        data.setdefault("model", {})["name"] = model_name
    if model_name := os.environ.get("OLLAMA_ORCHESTRATOR_MODEL"):
        data.setdefault("model", {})["name"] = model_name
    if model_name := os.environ.get("OLLAMA_SPECIALIST_MODEL"):
        data.setdefault("model", {})["specialist_name"] = model_name
    if host := os.environ.get("OLLAMA_ORCHESTRATOR_HOST"):
        data.setdefault("model", {})["orchestrator_host"] = host
    if host := os.environ.get("OLLAMA_SPECIALIST_HOST"):
        data.setdefault("model", {})["specialist_host"] = host
    if auth_header := os.environ.get("OLLAMA_AUTH_HEADER"):
        data.setdefault("model", {})["orchestrator_auth_header"] = auth_header
        data.setdefault("model", {})["specialist_auth_header"] = auth_header
    if auth_header := os.environ.get("OLLAMA_ORCHESTRATOR_AUTH_HEADER"):
        data.setdefault("model", {})["orchestrator_auth_header"] = auth_header
    if auth_header := os.environ.get("OLLAMA_SPECIALIST_AUTH_HEADER"):
        data.setdefault("model", {})["specialist_auth_header"] = auth_header
    if host := os.environ.get("SERVER_HOST"):
        data.setdefault("server", {})["host"] = host
    if port := os.environ.get("SERVER_PORT") or os.environ.get("PORT"):
        data.setdefault("server", {})["port"] = int(port)
    if data_dir := os.environ.get("APP_DATA_DIR"):
        data.setdefault("storage", {})["data_dir"] = data_dir
    if db_path := os.environ.get("APP_DB_PATH"):
        data.setdefault("storage", {})["db_path"] = db_path
    if (enabled := _env_bool("PARSING_ENABLED")) is not None:
        data.setdefault("parsing", {})["enabled"] = enabled
    if (enabled := _env_bool("PARSING_TEACHER_LOOP_ENABLED")) is not None:
        data.setdefault("parsing", {})["teacher_loop_enabled"] = enabled

    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_config(config_path: str = "config.yaml") -> AppConfig:
    """Return the application configuration, loaded once and cached."""
    path = Path(config_path)
    if not path.is_absolute():
        # Resolve relative to project root (two levels up from this file)
        path = Path(__file__).parent.parent / config_path
    return _load_config(path)
